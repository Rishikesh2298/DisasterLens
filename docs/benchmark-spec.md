# DisasterLens benchmark specification

Version: 0.1.0  
Scope: synthetic-scene generation, evaluation, and saved-run reporting

## Purpose and limits

The benchmark measures model outputs against synthetic scenes with known ground truth. Its results describe performance on those synthetic examples only. It is not an emergency-response or navigation system. A `clear` road result means only that the model detected no obstruction in the provided image ("No obstruction detected in imagery captured at time T").

## Input format

Both input files are JSON documents with a `scenes` array. Scene IDs must be unique within each document and join exactly across files. Every dataset scene declares a `split` of `dev` or `test`; evaluation selects one split before scoring. Predictions outside the selected dataset are rejected, and scenes without predictions count as invalid outputs and receive uncertain road predictions. Dataset records are validated with the shared Pydantic contracts before scoring.

Scene records contain:

- `scene_id`, `split`, and optional `difficulty` (`easy`, `medium`, `hard`).
- `truth.hazards`: `{type, bbox}` records; `bbox` is `[x1, y1, x2, y2]` in top-left-origin pixels.
- `truth.segments`: a map from segment ID to `blocked`, `partial`, or `clear`. The shared scene contract's `ground_truth.segment_status` shape is accepted and normalized to this field.
- `truth.damaged_building_count`, `truth.water_regions`, `truth.routes`, and `truth.zone_comparisons`.
- `road_graph.segments` and `road_graph.routes`: undirected graph edges and origin/destination pairs used for route impact.

Prediction records contain the same `scene_id` plus a `prediction` object with hazards, road segment statuses, building count, water regions, route answers, zone comparisons, optional confidence details, `valid_json`, and `latency_ms`. A vision `SceneAnalysis` using `segment_verdicts` is also accepted and adapted to road statuses and blocked-confidence probabilities. The top-level prediction document may declare `model_id`, `prompt_version`, and `is_mock`; scene-level metadata is inferred when consistent. Mixed model/prompt/mock runs are rejected. CLI flags can override model and prompt metadata, while `--mock` can mark any run as mock.

## Scoring

| Task | Definition |
|---|---|
| Hazard detection | Greedy, class-aware box matching in descending confidence order. Report aggregate and per-class precision, recall, F1 and macro-F1 at IoU 0.5 and 0.3. |
| Road status | Confusion matrix over blocked, partial, clear and uncertain; per-class F1, macro-F1, false-clear share, blocked miss rate, false-block rate and uncertain rate. Missing segment answers become uncertain. |
| Building count | Exact-match rate and mean absolute error. |
| Standing water | IoU-based greedy matching, precision, recall, F1 and mean IoU of matched pairs. |
| Route questions | Accuracy, obstructed-class F1 and accuracy on marked near-miss negatives. |
| Zone comparison | Accuracy over non-tie comparisons. |
| Calibration | Brier score for predicted blocked confidence and five fixed-width confidence bins. Lower Brier score is better. |
| Reliability | Valid-JSON rate and mean response latency where supplied. |
| Route impact | Reference shortest path after removing ground-truth blocks versus prediction-driven path; reports unsafe-route rate, unnecessary detour rate, extra distance and difficulty breakdown. |

The false-clear rate required by this benchmark is `(truly blocked and predicted clear) / all evaluated segments`. The conditional miss rate among truly blocked segments is separately reported as `blocked_miss_rate`.

## Route-impact policy

The local evaluator uses an undirected Dijkstra implementation until the shared routing engine is integrated. Predicted blocked edges are removed; uncertain, unknown, stale and partial edges receive a configurable graph penalty. An unsafe route contains a ground-truth blocked segment. An unnecessary detour is over 10% longer than the reference path and omits a clear reference segment. Disconnected paths are not classified as unsafe routes; they produce no selected path.

## Output contract

Each run writes `summary.json`, `failures.json`, and `per_scene.json` to its output directory. `summary.json` validates as `EvaluationSummary` and records run name, model ID, prompt version, split, mock flag, timestamp, scene count, task metrics, route impact and failure cases. Mock and real runs must remain distinct.

## Failure categories

Supported tags include `near_miss_false_block`, `false_block`, `false_clear`, `partial_confusion`, `missed_small_hazard`, `false_hazard`, `invalid_output`, `count_error`, and `wrong_zone`. Each record includes scene ID, difficulty, question/item, prediction and truth where available.

## Synthetic benchmark task generation

Every generated scene includes six structured benchmark tasks in `questions.json` alongside plain (`image_plain.png`) and labelled (`image_labelled.png`) 1024×1024 images:

1. **Blocked Road Segments:** Set of blocked segment IDs (`coverage >= 0.90`).
2. **Damaged Buildings:** Exact integer count of buildings with `damaged_building_only` or `building_spill`.
3. **Standing Water Regions:** Bounding boxes `[x1, y1, x2, y2]` of flood polygons.
4. **Route Obstruction (Positive):** Binary obstruction status and blocking segment IDs for routes crossing blocked segments.
5. **Route Obstruction (Near-Miss Negative):** Routes adjacent to near-miss decoys (`>= 8px` road clearance) that remain clear (`>= 25%` of route queries).
6. **Zone Hazard Comparison:** Pairwise comparison of cumulative polygon hazard area across city quadrants (`NW`, `NE`, `SW`, `SE`), excluding ties.

### Road obstruction thresholds

| Status | Cross-Sectional Coverage ($\theta$) | Operational Semantic | App Display Wording |
|---|---|---|---|
| `blocked` | $\theta \ge 0.90$ | Impassable corridor | Blocked |
| `partial` | $0.30 \le \theta < 0.90$ | Single-lane blockage / caution | Partial |
| `clear` | $\theta < 0.30$ | Impairment below threshold | No obstruction detected |
| `uncertain` | Conflicting model/heuristic | Disagreement or high variance | Uncertain |
| `stale` | Time delta exceeded | Outdated observation | Stale |
| `unknown` | No camera observation | Unobserved | Unknown |

### Leakage prevention

- `questions.json` stores `expected_answer` separately so evaluation runners strip ground truth before prompting models.
- Prompt strings contain zero coordinate hints or segment statuses.
- `datasets/v1/manifest.json` records SHA-256 hashes for all generated files for reproducible verification.

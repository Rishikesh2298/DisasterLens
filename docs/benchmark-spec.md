# DisasterLens Benchmark Specification: Task Definitions & Scoring Protocol

**Track:** Visual Task Factory  
**Version:** 1.0  
**Owner:** Benchmark Task Owner (Tejash / Rishikesh)

---

## 1. Benchmark Overview

The DisasterLens benchmark evaluates the spatial reasoning capabilities of vision and multimodal language models in simulated disaster response contexts. Rather than testing generic object classification, it measures whether a model understands **functional obstruction**—the geometric relationship between physical hazards and transportation corridors.

> [!WARNING]
> Results obtained on this benchmark reflect model spatial reasoning on synthetic top-down vector layouts. They do not certify or validate model performance on real aerial, satellite, or drone imagery during actual emergency operations.

---

## 2. Six Benchmark Task Types

```
Task 1: Blocked Road Segments  --> Set comparison (F1 / Precision / Recall)
Task 2: Damaged Buildings       --> Exact count & Mean Absolute Error (MAE)
Task 3: Standing Water Regions  --> Bounding Box IoU @ 0.50
Task 4: Route Obstruction (Pos) --> Binary classification & blocking segment identification
Task 5: Route Obstruction (Neg) --> Binary discrimination under near-miss distractor conditions
Task 6: Zone Hazard Comparison  --> Pairwise area ranking (excluding exact ties)
```

### Task 1: Blocked Road Segments
- **Prompt:** *"Which road segments are blocked in this scene?"*
- **Model Output:** List of segment IDs (e.g. `["SEG-004", "SEG-012"]`).
- **Ground Truth:** All segments with maximum cross-sectional coverage $\ge 0.90$.

### Task 2: Damaged Buildings
- **Prompt:** *"How many buildings are visibly damaged in this scene?"*
- **Model Output:** Non-negative integer count.
- **Ground Truth:** Buildings flagged with `damaged_building_only` or `building_spill`.

### Task 3: Water Regions
- **Prompt:** *"Locate all regions with standing water in this scene."*
- **Model Output:** Array of bounding boxes `[x_min, y_min, x_max, y_max]`.
- **Ground Truth:** Bounding boxes of flood polygons on roads, blocks, or parks.

### Task 4 & 5: Route Obstruction (Positive & Near-Miss Negative)
- **Positive Prompt:** *"Is the route from N1 to N16 obstructed? If yes, identify the blocking road segments."*
- **Negative Prompt:** *"Is the route from N2 to N14 obstructed? If yes, identify the blocking road segments. Note: a hazard near a road does not necessarily block it."*
- **Ground Truth:**
  - Positive: $\ge 1$ segment on the route is `BLOCKED`. Expected answer: `{"obstructed": true, "blocking_segments": [...]}`.
  - Negative: All segments on the route are `CLEAR`, but at least one segment has a neighboring near-miss hazard ($\ge 8\text{px}$ clearance). Expected answer: `{"obstructed": false, "blocking_segments": []}`.
  - Near-miss cases compose $\ge 25\%$ of all route queries to test false-block tendencies.

### Task 6: Zone Comparison
- **Prompt:** *"Which zone has more visible hazard area: NW or SE?"*
- **Model Output:** Zone identifier (`NW`, `NE`, `SW`, `SE`).
- **Ground Truth:** Cumulative polygon area $\sum \text{Area}(H_z)$ per quadrant. Ties ($|\Delta| < 1.0\text{px}^2$) are excluded.

---

## 3. Road Obstruction Classification Criteria

| Status | Cross-Sectional Coverage ($\theta$) | Operational Semantic | App Display Wording |
|---|---|---|---|
| **BLOCKED** | $\theta \ge 0.90$ | Impassable corridor | **Blocked** |
| **PARTIAL** | $0.30 \le \theta < 0.90$ | Single-lane blockage / caution | **Partial** |
| **CLEAR** | $\theta < 0.30$ | Impairment below threshold | **No obstruction detected** |
| **UNCERTAIN** | Conflicting model/heuristic | Disagreement or high variance | **Uncertain** |
| **STALE** | Time delta exceeded | Outdated observation | **Stale** |
| **UNKNOWN** | No camera observation | Unobserved | **Unknown** |

---

## 4. Leakage Prevention Protocol

- `questions.json` stores hidden answers under `expected_answer` which is stripped before presentation to evaluation harnesses.
- Prompt text contains zero quantitative coordinate hints or ground-truth segment statuses.
- Ground truth is computed exclusively from vector primitives prior to image rendering.
- `datasets/v1/manifest.json` provides cryptographic SHA-256 verification of all files to guarantee tamper-evident reproducibility.

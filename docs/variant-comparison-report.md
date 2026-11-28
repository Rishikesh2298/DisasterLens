# Prompt v2 Variant Comparison Report
## DisasterLens — Day 4 | Vision AI Engine (`feat/divyanshu/vision-ai-engine`)

> [!IMPORTANT]
> All metrics are computed offline against the 20 development scenes (S-0001 to S-0020) using
> pre-recorded predictions. No new Gemini API calls were made.

---

## Evaluation Setup

| Item | Value |
|---|---|
| Model | `gemini-3.5-flash-lite` |
| Prompt version | v2 |
| Scenes | S-0001 to S-0020 (all 20 dev scenes) |
| Segments per scene | 24 |
| Total segments evaluated | 480 |
| Ground-truth source | `datasets/v1/S-XXXX/ground_truth.json` |
| Plain predictions | `results/predictions/dev/gemini-v2-plain-batch/` |
| Labelled predictions | `results/predictions/dev/gemini-v2-labelled-batch/` |
| Evaluation script | `scripts/evaluate_predictions.py` |
| Eval reports | `results/predictions/dev/eval_plain_v2.json`, `eval_labelled_v2.json` |

> [!NOTE]
> Hazard bounding-box metrics (IoU, detection F1) cannot be computed because
> `ground_truth.json` does not contain hazard polygon or bbox coordinates.
> Only segment-status classification metrics are reported.

---

## Ground-Truth Class Distribution (480 total segments)

| Status | Count | % |
|---|---|---|
| CLEAR | 436 | 90.8% |
| BLOCKED | 35 | 7.3% |
| PARTIAL | 9 | 1.9% |
| UNCERTAIN | 0 | — (not a GT class) |

---

## Head-to-Head Metrics

### Top-line

| Metric | Plain v2 | Labelled v2 | Δ (Lab − Plain) |
|---|---|---|---|
| **Overall Accuracy** | 0.8833 | **0.9354** | +0.0521 |
| **Macro-F1** | 0.4904 | **0.7547** | +0.2643 |
| **BLOCKED Recall** | 0.0286 | **0.3714** | +0.3428 |
| UNCERTAIN Rate | 0.0000 | 0.0000 | — |
| Segments Correct | 424 / 480 | **449 / 480** | +25 |

### Per-Class Detail

| Class | GT Count | Metric | Plain v2 | Labelled v2 |
|---|---|---|---|---|
| **CLEAR** | 436 | Precision | 0.9116 | 0.9376 |
| | | Recall | 0.9702 | **1.0000** |
| | | F1 | 0.9400 | **0.9678** |
| **BLOCKED** | 35 | Precision | 0.0714 | **1.0000** |
| | | Recall | 0.0286 | **0.3714** |
| | | F1 | 0.0408 | **0.5416** |
| **PARTIAL** | 9 | Precision | 0.0000 | 0.0000 |
| | | Recall | 0.0000 | 0.0000 |
| | | F1 | — | — |

### Confusion Matrices

**Plain v2** (rows = ground truth, cols = predicted)

| GT \ Pred | CLEAR | BLOCKED | PARTIAL | UNCERTAIN |
|---|---|---|---|---|
| CLEAR | 423 | 12 | 1 | 0 |
| BLOCKED | 33 | **1** | 1 | 0 |
| PARTIAL | 8 | 1 | **0** | 0 |
| UNCERTAIN | 0 | 0 | 0 | 0 |

**Labelled v2** (rows = ground truth, cols = predicted)

| GT \ Pred | CLEAR | BLOCKED | PARTIAL | UNCERTAIN |
|---|---|---|---|---|
| CLEAR | 436 | 0 | 0 | 0 |
| BLOCKED | 20 | **13** | 2 | 0 |
| PARTIAL | 9 | 0 | **0** | 0 |
| UNCERTAIN | 0 | 0 | 0 | 0 |

---

## Key Observations

### 1. Labelled variant is strictly superior across all measured metrics
- **+5.2 pp accuracy**, **+26.4 pp macro-F1**, **+34.3 pp BLOCKED recall**.
- The labelled image provides segment annotations Gemini can reference directly,
  dramatically improving its ability to identify which specific segment is blocked.

### 2. Plain variant severely under-detects BLOCKED segments
- Plain v2 correctly identifies only **1 out of 35** BLOCKED segments (2.9% recall).
- 33 BLOCKED segments are misclassified as CLEAR — a critical safety failure.
- The model predicts BLOCKED 14 times on the plain image, but 13 of those are
  false positives (clear segments called blocked).

### 3. Labelled variant has perfect BLOCKED precision (0 false alarms)
- Every BLOCKED prediction from the labelled variant is correct (13 TP, 0 FP).
- 22 BLOCKED segments are still missed (called CLEAR), leaving recall at 37%.
- This is a recall problem, not a specificity problem.

### 4. PARTIAL is not detected by either variant
- Both variants predict PARTIAL a combined total of 4 times with zero true positives.
- 9 PARTIAL segments exist in ground truth; none are correctly identified.
- Root cause: Gemini tends to collapse ambiguous partial coverage to either CLEAR or BLOCKED.

### 5. No UNCERTAIN predictions from either variant
- Prompt v2's explicit instruction to avoid UNCERTAIN when segment IDs are labelled
  worked for the labelled variant; the plain variant also avoids UNCERTAIN, though at
  the cost of overconfident CLEAR predictions on blocked segments.

---

## Recommendation

> [!IMPORTANT]
> **Labelled v2 is the preferred variant.** It achieves 13× higher BLOCKED recall,
> perfect BLOCKED precision, higher overall accuracy, and higher macro-F1 than plain v2.

The labelled variant should be used as the primary inference path whenever a
labelled image (with segment IDs overlaid) is available.

The plain variant performs acceptably only for CLEAR detection and should not be
used for primary safety-critical routing without additional post-processing.

### Outstanding Gaps (not addressed by prompt tuning alone)
1. **PARTIAL detection** — neither variant identifies PARTIAL blockage. This may require
   explicit training examples or a separate classification step.
2. **Plain BLOCKED recall** — the absence of segment labels in plain images makes
   spatial localisation unreliable. Consider always using the labelled path in production.
3. **Labelled BLOCKED recall at 37%** — further v2 prompt tuning on a held-out test set
   (not the dev set) is needed once the team is ready to move to v3.

---

*Generated: Day 4 evaluation, branch `feat/divyanshu/vision-ai-engine`.*
*Do not use dev-set metrics to tune prompts.*

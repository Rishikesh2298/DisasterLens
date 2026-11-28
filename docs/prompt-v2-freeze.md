# Prompt v2 Freeze Record
## DisasterLens — Day 4 | Vision AI Engine (`feat/divyanshu/vision-ai-engine`)

> [!IMPORTANT]
> This document records the frozen state of Prompt v2 as evaluated on the 20 development scenes.
> Do **not** modify the prompt files after this freeze without updating this record.
> Do **not** tune prompts using test-set data.

---

## Frozen Files

| File | Path |
|---|---|
| Plain image prompt | `dl/vision/prompts/v2/plain.txt` |
| Labelled image prompt | `dl/vision/prompts/v2/labelled.txt` |

## SHA-256 Checksums

| Variant | SHA-256 |
|---|---|
| `plain.txt` | `83C09414C2EFBCB6BACD71C778312E8322CCFCB118B193DEE5FA83065440F6CE` |
| `labelled.txt` | `D8D08E1E00F9884D03E2054E80620F18211E5AF4E3AC60988AA406B5F1810B71` |

> [!NOTE]
> Checksums computed with PowerShell `Get-FileHash -Algorithm SHA256` on 2026-11-27.
> Verify before any downstream use:
> ```powershell
> Get-FileHash dl\vision\prompts\v2\plain.txt -Algorithm SHA256
> Get-FileHash dl\vision\prompts\v2\labelled.txt -Algorithm SHA256
> ```

---

## Prompt Loader

Prompts are loaded at runtime by `dl/vision/providers/gemini.py` via:

```python
prompt_path = Path("dl/vision/prompts") / prompt_version / f"{image_variant}.txt"
```

Where:
- `prompt_version` = `"v2"` (passed through `runner.py` → `gemini.py`)
- `image_variant` = `"plain"` or `"labelled"`

No fallback to v1 exists; a missing file raises `FileNotFoundError`.

---

## Evaluation Summary (Dev Set, 20 Scenes)

| Metric | Plain v2 | Labelled v2 |
|---|---|---|
| Scenes evaluated | 20 / 20 | 20 / 20 |
| Total segments | 480 | 480 |
| Overall accuracy | 0.8833 | **0.9354** |
| Macro-F1 | 0.4904 | **0.7547** |
| BLOCKED Recall | 0.0286 | **0.3714** |
| BLOCKED Precision | 0.0714 | **1.0000** |
| PARTIAL Recall | 0.0000 | 0.0000 |
| UNCERTAIN Rate | 0.0000 | 0.0000 |
| Valid JSON rate | 20/20 | 20/20 |
| Avg latency (ms) | ~3,980 | ~4,120 |

> [!IMPORTANT]
> **Recommended variant: Labelled v2.**
> The labelled variant outperforms plain v2 on every safety-critical metric.
> BLOCKED precision is perfect (1.0) with no false alarms.

---

## Evaluation Files

| File | Description |
|---|---|
| `results/predictions/dev/gemini-v2-plain-batch/` | 20 plain-image predictions |
| `results/predictions/dev/gemini-v2-labelled-batch/` | 20 labelled-image predictions |
| `results/predictions/dev/eval_plain_v2.json` | Full plain evaluation report |
| `results/predictions/dev/eval_labelled_v2.json` | Full labelled evaluation report |
| `scripts/evaluate_predictions.py` | Offline evaluation script |
| `docs/variant-comparison-report.md` | Detailed comparison analysis |

---

## Prompt v2 Design Decisions

### Both variants
- Neutral opening: detect visible hazards **only** when supported by image evidence.
- Flood requires explicit standing-water visual evidence; shadows, stains, dark asphalt
  and vegetation do not qualify.
- Debris: look for materials that have fallen onto or across the roadway.
- Bounding-box ordering constraint: `[x_min, y_min, x_max, y_max]` with `x_min ≤ x_max`
  and `y_min ≤ y_max`.
- Avoid UNCERTAIN when segment visibility can be assessed.

### Plain variant (`plain.txt`)
- Uses cardinal-direction spatial references (north, south, east, west, centre).
- Road segments referenced by spatial location.

### Labelled variant (`labelled.txt`)
- Instructs model to use printed segment ID labels visible in the image.
- Road verdict must reference the labelled segment ID associated with the obstructed corridor.
- Explicit instruction not to use UNCERTAIN when labels are visible.

---

## Status

| Item | Status |
|---|---|
| Prompt files written | ✅ Done |
| Checksums recorded | ✅ Done |
| Dev-set evaluation run | ✅ Done (2026-11-27) |
| Preferred variant identified | ✅ Labelled v2 |
| Prompt frozen (do not modify) | ✅ |
| Ready for v3 iteration | ⏳ Pending — use held-out test set, not dev set |

---

*Branch: `feat/divyanshu/vision-ai-engine` | Day 4 completion.*

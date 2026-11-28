# `analyze_observation` API Handoff Document
## DisasterLens — Day 4 | Vision AI Engine → Backend Integration

> [!IMPORTANT]
> This document is for **Rajneesh** (backend/observation-upload endpoint) and other
> consumers of the Vision AI engine. It covers the complete `analyze_observation`
> contract as of Day 4, branch `feat/divyanshu/vision-ai-engine`.

---

## Import Path

```python
from dl.vision.api import analyze_observation, ObservationResult
```

Source: [`dl/vision/api.py`](../dl/vision/api.py)

---

## Function Signature

```python
def analyze_observation(
    image: bytes | str | Path | Any,
    zone_geometry: Scene | Collection[RoadSegment] | dict[str, Any] | Any,
    mode: str = "mock",
    *,
    prompt_version: str = "v1",
    **kwargs: Any,
) -> ObservationResult:
```

---

## Parameters

### `image` — _required_

The uploaded camera observation image. Accepts:

| Type | Description |
|---|---|
| `bytes` | Raw image bytes (non-empty) |
| `str` or `Path` | Filesystem path to the image file |
| file-like object | Any object with a `.read()` method |

```python
# Examples
result = analyze_observation(image=b"\x89PNG...", ...)
result = analyze_observation(image="datasets/v1/S-0001/image_plain.png", ...)
result = analyze_observation(image=Path("datasets/v1/S-0001/image_plain.png"), ...)
with open("image.png", "rb") as f:
    result = analyze_observation(image=f, ...)
```

---

### `zone_geometry` — _required_

The road-network geometry for the observation zone. Accepts:

| Type | Description |
|---|---|
| `Scene` | Contract-valid scene object (`dl.contracts.scene.Scene`) |
| `list[RoadSegment]` | Sequence of road segment objects |
| `dict` | Dict with `"segments"` key (optionally `"nodes"`, `"ground_truth"`) |

> [!CAUTION]
> **Never pass `ground_truth.json` contents directly** to this parameter.
> Ground truth is used only offline for evaluation. It must not reach the vision model.
> `datasets/v1/S-XXXX/ground_truth.json` is evaluation-only data.

Recommended: load scene geometry from `scene.json` via the scene loader:

```python
from dl.vision.runner import SceneLoader
scene = SceneLoader(Path("datasets/v1/S-0001"), split="dev").load_scene()
result = analyze_observation(image=img_bytes, zone_geometry=scene, ...)
```

---

### `mode` — `"mock"` | `"cached"` | `"live"` (default: `"mock"`)

| Mode | Description |
|---|---|
| `"mock"` | Ground-truth oracle adapter. No API key required. Use for unit tests and CI. |
| `"cached"` | SHA-256 response cache wrapping the live provider. Falls back to mock if no live provider is configured. |
| `"live"` | Real Gemini API call. Requires `GEMINI_API_KEY` environment variable. |

> [!WARNING]
> `"live"` mode requires `$env:GEMINI_API_KEY` to be set and a registered provider.
> If the provider is not registered, `NotImplementedError` is raised with a descriptive message.

---

### `prompt_version` — string (default: `"v1"`)

Prompt version to pass to the vision provider. Use `"v2"` for the Day 4 frozen prompt.

```python
result = analyze_observation(..., prompt_version="v2")
```

---

### `**kwargs` — optional keyword arguments

| Kwarg | Description |
|---|---|
| `provider` | Vision provider key (default: `"gemini"` or `$VISION_PROVIDER`). |
| `model` | Model identifier (e.g. `"gemini-3.5-flash-lite"`). |
| `image_variant` | `"plain"` or `"labelled"` — selects prompt file variant. |
| `adapter` | Pre-built `VisionAdapter` instance (overrides automatic adapter resolution). |
| `cache_dir` | Cache directory path for `"cached"` mode. |
| `inner_adapter` | Inner adapter for `"cached"` mode. |

---

## Return Value: `ObservationResult`

```python
class ObservationResult(BaseModel):
    hazards: list[PredictedHazard]            # Detected hazards
    direct_verdicts: dict[str, SegmentVerdict] # Raw model segment verdicts
    mapped_verdicts: dict[str, RoadMappingResult] # Geometric mapping results
    guarded_verdicts: dict[str, SegmentVerdict]   # Final safety-guarded verdicts
    model_id: str                              # Model used
    prompt_version: str                        # Prompt version tag
    latency_ms: int                            # Wall-clock execution time (ms)
    metadata: dict[str, Any]                   # Model/latency metadata dict
```

> [!NOTE]
> `ObservationResult` supports both attribute access (`result.hazards`) and
> dictionary-style access (`result["hazards"]`, `result.get("hazards", [])`).
> Convenience aliases: `result.latency` → `latency_ms`, `result.final_verdicts` → `guarded_verdicts`.

---

## Sub-Contract Types

### `PredictedHazard` (`dl.contracts.vision.PredictedHazard`)

```python
class PredictedHazard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: HazardType        # e.g. "debris", "flood", "road_damage"
    bbox: Box               # [x_min, y_min, x_max, y_max] — ordered coordinates
    confidence: float       # 0.0 – 1.0
```

Dump all fields safely: `hazard.model_dump(mode="json")` → `{"type": "debris", "bbox": [...], "confidence": 0.9}`

### `SegmentVerdict` (`dl.contracts.vision.SegmentVerdict`)

```python
class SegmentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: RoadStatus      # "clear" | "blocked" | "partial" | "uncertain"
    confidence: float       # 0.0 – 0.85 (capped by contract)
    evidence: str           # Natural-language explanation
    visible: bool | None    # Whether segment was visible in image
```

> [!NOTE]
> `extra="forbid"` is set on **all** contracts. Do not add extra fields to these models.

### `RoadStatus` enum values
`"clear"` | `"blocked"` | `"partial"` | `"uncertain"`

### `HazardType` enum values
`"debris"` | `"flood"` | `"road_damage"` (and others — check `dl/contracts/enums.py`)

---

## Usage Examples

### Mock mode (unit tests, CI — no API key needed)

```python
from pathlib import Path
from dl.vision.api import analyze_observation

result = analyze_observation(
    image=Path("datasets/v1/S-0001/image_plain.png"),
    zone_geometry=scene,  # Scene from SceneLoader(Path("datasets/v1/S-0001"), split="dev").load_scene()
    mode="mock",
    prompt_version="v2",
)

print(f"Hazards found: {len(result.hazards)}")
for seg_id, verdict in result.guarded_verdicts.items():
    print(f"  {seg_id}: {verdict.status} (conf={verdict.confidence:.2f})")
```

### Live mode (requires GEMINI_API_KEY)

```python
import os
from dl.vision.api import analyze_observation

assert os.getenv("GEMINI_API_KEY"), "Set GEMINI_API_KEY before live mode"

result = analyze_observation(
    image=image_bytes,            # bytes from observation upload
    zone_geometry=scene,          # Scene loaded from scene.json
    mode="live",
    prompt_version="v2",
    provider="gemini",
    model="gemini-3.5-flash-lite",
    image_variant="labelled",     # preferred variant per Day 4 evaluation
)
```

### Cached mode

```python
result = analyze_observation(
    image=image_bytes,
    zone_geometry=scene,
    mode="cached",
    prompt_version="v2",
    cache_dir="results/predictions/dev/gemini-v2-labelled-batch/.cache",
    image_variant="labelled",
    provider="gemini",
)
```

---

## Accessing Results in Backend

```python
# Safety-guarded final verdicts (use these for routing decisions)
for seg_id, verdict in result.guarded_verdicts.items():
    if verdict.status == "blocked":
        mark_road_blocked(seg_id, evidence=verdict.evidence)

# Detected hazards
for hazard in result.hazards:
    h = hazard.model_dump(mode="json")
    store_hazard(type=h["type"], bbox=h["bbox"], confidence=h["confidence"])

# Metadata
print(result.model_id, result.prompt_version, result.latency_ms)
meta = result.metadata  # dict with "model_id", "latency_ms", etc.
```

---

## Execution Modes Decision Guide

```
Observation arrives at endpoint
        │
        ▼
  Is GEMINI_API_KEY set?
        │
   Yes  │  No
        │   └──► mode="mock" (testing only)
        ▼
  Is a cached response available?
        │
   Yes  │  No
        │   └──► mode="live"
        ▼
      mode="cached"
```

> [!TIP]
> For the production observation-upload endpoint, use `mode="cached"` first (checks
> SHA-256 cache), falling through to `mode="live"` if no cached response exists.
> This minimises Gemini API costs during development.

---

## Error Cases

| Exception | Cause | Fix |
|---|---|---|
| `ValueError` | Invalid `mode` or empty image | Check mode spelling; ensure image is non-empty |
| `FileNotFoundError` | Image path does not exist | Verify file path before calling |
| `TypeError` | Unsupported `zone_geometry` type | Pass `Scene`, `list[RoadSegment]`, or dict with `"segments"` key |
| `NotImplementedError` | `mode="live"` but provider not configured | Set `GEMINI_API_KEY` and ensure `gemini` is registered |
| `pydantic.ValidationError` | Contract field violation | Do not add extra fields; check enum values |

---

## Relevant Tests

| File | Coverage |
|---|---|
| `tests/test_vision_api.py` | `analyze_observation` all three modes, error paths |
| `tests/test_vision_gemini.py` | Live Gemini adapter, prompt loading, response parsing |
| `tests/test_vision_parser.py` | JSON repair, bbox normalization, diagnostic logging |
| `scripts/smoke_test.py` | End-to-end single-scene smoke test |

Run the full test suite (no API key required):
```powershell
C:\Disaster\.venv\Scripts\python.exe -m pytest -q tests/
```

---

## Preferred Configuration for Day 4+

| Setting | Value |
|---|---|
| `prompt_version` | `"v2"` |
| `image_variant` | `"labelled"` (preferred) or `"plain"` |
| `model` | `"gemini-3.5-flash-lite"` |
| `provider` | `"gemini"` |
| BLOCKED recall (labelled v2) | 0.3714 (dev set) |
| BLOCKED precision (labelled v2) | 1.0000 (dev set) |

---

*Branch: `feat/divyanshu/vision-ai-engine` | Day 4 completion.*
*Contact: Divyanshu (vision-ai-engine owner).*

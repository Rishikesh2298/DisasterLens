# DisasterLens Generator Documentation

The `dl/generator` module implements the **Visual Task Factory** for DisasterLens: deterministic synthetic disaster-city generation, hazard placement, exact geometric ground-truth computation, independent raster validation, benchmark question generation, and rendering.

---

## 1. Safety Notice & Research Scope

> [!WARNING]
> **SAFETY NOTICE:** DisasterLens is a research prototype operating on synthetic (computer-generated) scenes. It is **NOT** a certified navigation, emergency-response, or life-safety system.
> It never claims that a road or route is "safe". It reports strictly that:
> *"No obstruction detected in imagery captured at time T."*
> Synthetic imagery cannot establish water depth, structural integrity, underground damage, or official emergency road closures.

---

## 2. Architecture & Components

```
dl/generator/
├── __init__.py
├── __main__.py          # Entry point for python -m dl.generator.build
├── build.py             # Dataset build pipeline & CLI
├── city.py              # Deterministic city grid & road network layout
├── geometry.py           # Perpendicular cross-section slicing (20 cuts)
├── ground_truth.py      # Ground-truth engine (90%/30% classification rule)
├── hazards.py           # 5 hazard classes, 7 placement specifications
├── questions.py         # 6 benchmark task generators with hidden answers
├── render.py            # 2x supersampled PNG rendering (plain & labelled)
├── scenario_pack.py     # 6x6 4-camera demo city with T0-T3 timeline
└── validate.py          # Independent raster-based validator
```

---

## 3. Specifications & Determinism

### Deterministic Randomness
- Base seed convention: Scene `i` uses seed `2026 + i`.
- Pure deterministic execution via `random.Random(seed)` and `numpy.random.default_rng(seed)`.
- Canonical JSON serialization with sorted keys guarantees stable SHA-256 hashes across repeated builds.

### Grid Configurations
- **Easy (4×4):** 16 intersections (`N1`..`N16`), 24 road segments (`SEG-001`..`SEG-024`), 1–2 large high-contrast hazards.
- **Medium (5×5):** 25 intersections (`N1`..`N25`), 40 road segments (`SEG-001`..`SEG-040`), 2–4 hazards including near-miss decoys and water on parks.
- **Hard (6×6):** 36 intersections (`N1`..`N36`), 60 road segments (`SEG-001`..`SEG-060`), 3–6 hazards with building spills, road damage severity, noise, and JPEG compression artefacts.

---

## 4. Ground-Truth Methodology (The 20-Cross-Section Rule)

For every road segment:
1. Divide the segment centerline into 20 equally spaced points.
2. Construct perpendicular cross-sections across the entire 40px road width.
3. Intersect each cross-section with the union of road-affecting hazard polygons using Shapely 2.
4. Compute coverage fraction: $\text{coverage} = \frac{\text{covered length}}{\text{road width}}$.
5. Compute worst-case coverage across all 20 cross-sections:
   - $\ge 0.90 \implies \mathbf{BLOCKED}$
   - $0.30 \le \text{coverage} < 0.90 \implies \mathbf{PARTIAL}$
   - $< 0.30 \implies \mathbf{CLEAR}$ (reported as *"No obstruction detected"*)
6. Severity overrides:
   - `road_damage` with `minor` severity is capped at `PARTIAL`.
   - `damaged_building_only` never blocks a road.
   - `near_miss_decoy` hazards maintain $\ge 8\text{px}$ clearance and never block a road.

---

## 5. Independent Raster Validator (`validate.py`)

The validator does **not** invoke `ground_truth.py`. It independently verifies ground truth through scanline polygon rasterization on a $1024 \times 1024$ boolean NumPy grid:
1. Segments and hazards are independently rasterized.
2. Perpendicular pixel slices are computed along each segment.
3. Road status is independently re-classified and verified against `ground_truth.json`.
4. Validates graph connectivity, unique IDs, non-overlapping near-miss placement, and schema integrity.

---

## 6. CLI Usage

### Build full 100-scene dataset:
```bash
python -m dl.generator.build --n 100 --seed 2026 --output datasets/v1
```

### Build 20 development scenes:
```bash
python -m dl.generator.build --n 20 --seed 2026 --output datasets/v1
```

### Generate demo city scenario pack:
```bash
python -m dl.generator.scenario_pack
```

### Run test suite:
```bash
pytest tests/test_generator.py -v
```

# DisasterLens Dataset Card: v1.0 Synthetic Benchmark

## 1. Summary

The **DisasterLens v1.0** dataset is a benchmark designed to evaluate multimodal vision-language and foundation models on spatial disaster scene understanding and road-obstruction reasoning.

> [!CAUTION]
> **RESEARCH PROTOTYPE DISCLAIMER:**  
> DisasterLens is an artificial, synthetic benchmark. All scenes, cities, roads, buildings, and hazard overlays are computer-generated. The dataset does **not** evaluate real-world disaster imagery or structural integrity. A road marked `CLEAR` indicates strictly:  
> *"No obstruction detected in imagery captured at time T."*  
> It must never be used for certified emergency response, navigation, or life-critical routing.

---

## 2. Dataset Composition

- **Total Scenes:** 100 scenes (`S-0001` through `S-0100`)
- **Splits:**
  - **Development (tuning) split:** Scenes `S-0001` to `S-0030` (30 scenes)
  - **Test split (frozen benchmark):** Scenes `S-0031` to `S-0100` (70 scenes)
- **Difficulty Distribution:**
  - **Easy:** 30 scenes (4×4 grid, 1–2 large hazards, high contrast)
  - **Medium:** 35 scenes (5×5 grid, 2–4 hazards, partial blocks, near-miss decoys, water on parks)
  - **Hard:** 35 scenes (6×6 grid, 3–6 hazards, building rubble spills, road cracks/craters, visual noise/blur/JPEG artefacts)
- **Base Seed:** 2026 (Scene $i$ uses seed $2026 + i$). Fully reproducible.

---

## 3. Hazard Classes & Specifications

| Hazard Class | Visual Representation | Placement Specifications |
|---|---|---|
| **Flood** | Translucent blue with ripple markings | `block_full`, `block_partial`, `near_miss_decoy`, `water_on_park` |
| **Debris** | Irregular textured brown/grey polygons | `block_full`, `block_partial`, `near_miss_decoy`, `building_spill` |
| **Fallen Tree** | Dark green elongated canopy with brown trunk | `block_full`, `block_partial`, `near_miss_decoy` |
| **Road Damage** | High-contrast dark asphalt fractures & craters | `road_damage` (`minor` $\to$ PARTIAL, `major` $\to$ BLOCKED) |
| **Damaged Building** | Building roof with red tint and high-contrast 'X' | `damaged_building_only`, `building_spill` |

---

## 4. Ground-Truth & Validation Methodology

### 20-Cross-Section Rule
Each road segment is sliced into 20 perpendicular cross-sections along its centerline spanning its full width ($40\text{px} \approx 8\text{m}$). The worst-case coverage fraction determines status:
- $\ge 90\% \implies \text{BLOCKED}$
- $30\% \text{ to } 90\% \implies \text{PARTIAL}$
- $< 30\% \implies \text{CLEAR}$

### Independent Raster Verification
Every generated scene is independently validated by a secondary raster pipeline (`dl/generator/validate.py`) which rasterizes polygons onto a boolean NumPy grid and re-computes slice coverage. Mismatches abort the build pipeline.

---

## 5. Directory Structure

```
datasets/v1/
├── manifest.json            # SHA-256 hashes, splits, difficulty, seeds
├── stats.json               # Aggregated hazard, segment status, and question stats
├── S-0001/
│   ├── scene.json           # Complete vector geometry (intersections, roads, buildings, parks, hazards)
│   ├── ground_truth.json    # Exact segment statuses, damaged buildings, water areas, zone areas
│   ├── questions.json       # 6 benchmark task questions and hidden expected answers
│   ├── image_plain.png      # 1024x1024 RGB image (roads, buildings, parks, hazards)
│   └── image_labelled.png   # 1024x1024 RGB image with segment ID labels
└── ...
```

---

## 6. Benchmark Tasks

1. **Blocked Road Identification:** Set of blocked segment IDs.
2. **Damaged Building Counting:** Exact count of visibly damaged buildings.
3. **Standing Water Localization:** Bounding boxes of standing water bodies.
4. **Route Obstruction (Positive):** Determining if a specified route between two nodes is blocked.
5. **Route Obstruction (Near-Miss Negative):** Testing spatial discrimination when hazards are adjacent to but not obstructing the route ($\ge 25\%$ of route queries).
6. **Zone Hazard Comparison:** Comparing total visible hazard area between quadrants.

---

## 7. Known Limitations

1. **Synthetic Planar Geometry:** 2D top-down view without 3D elevations, slope, or lighting shadows.
2. **Simplified Fluid Dynamics:** Water regions are geometric boundaries rather than simulated hydrodynamic flows.
3. **No Sensor Imperfections:** Beyond synthetic Gaussian noise and JPEG compression, camera lens distortion and meteorological effects (heavy rain/fog) are not modelled.

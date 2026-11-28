"""
Demo city scenario pack.

Generates a 6×6 city with four camera views (one per quadrant) and
T0–T3 events for the ScenarioPlayer.
"""

from __future__ import annotations

import json
import os
import random as _random

from dl.generator.city import generate_city
from dl.generator.ground_truth import compute_ground_truth
from dl.generator.hazards import (
    _bbox,
    _place_block_full,
    _place_near_miss,
    _poly_points,
)
from dl.generator.models import Difficulty, Hazard, HazardType, PlacementSpec
from dl.generator.render import render_scene

DEMO_SEED = 20261127
SCENARIO_DIR = "scenarios/demo_city"


def _make_camera_views(scene):
    """Define four camera views covering the four quadrants."""
    cx = scene.image_width / 2
    cy = scene.image_height / 2
    views = [
        {
            "camera_id": "synthetic_camera_1",
            "zone": "NW",
            "viewport": {"x_min": 0, "y_min": 0, "x_max": cx, "y_max": cy},
            "covered_segments": [
                s.id for s in scene.road_segments
                if s.zone.value == "NW"
            ],
        },
        {
            "camera_id": "synthetic_camera_2",
            "zone": "NE",
            "viewport": {"x_min": cx, "y_min": 0, "x_max": scene.image_width, "y_max": cy},
            "covered_segments": [
                s.id for s in scene.road_segments
                if s.zone.value == "NE"
            ],
        },
        {
            "camera_id": "synthetic_camera_3",
            "zone": "SW",
            "viewport": {"x_min": 0, "y_min": cy, "x_max": cx, "y_max": scene.image_height},
            "covered_segments": [
                s.id for s in scene.road_segments
                if s.zone.value == "SW"
            ],
        },
        {
            "camera_id": "synthetic_camera_4",
            "zone": "SE",
            "viewport": {"x_min": cx, "y_min": cy, "x_max": scene.image_width, "y_max": scene.image_height},
            "covered_segments": [
                s.id for s in scene.road_segments
                if s.zone.value == "SE"
            ],
        },
    ]
    return views


def build_demo_city(output_dir: str = SCENARIO_DIR):
    """Build the demo city scenario pack."""
    os.makedirs(output_dir, exist_ok=True)
    from PIL import Image
    from shapely.ops import unary_union

    from dl.generator.hazards import _seg_poly

    rng = _random.Random(DEMO_SEED)

    # 1. Generate base 6×6 city
    scene = generate_city("DEMO-001", DEMO_SEED, Difficulty.HARD)

    # Precompute buffered union for near-miss safety
    roads_buffered = unary_union([_seg_poly(s) for s in scene.road_segments]).buffer(8.5)

    # 2. Place explicit hazards matching the T0–T3 demonstration sequence:
    # T1: Flood across one main road segment in NW (synthetic_camera_1)
    nw_roads = [s for s in scene.road_segments if s.zone.value == "NW"]
    flood_seg = nw_roads[0] if nw_roads else scene.road_segments[0]
    poly_flood = _place_block_full(flood_seg, rng, HazardType.FLOOD)
    h_flood = Hazard(
        id="H-001",
        type=HazardType.FLOOD,
        placement=PlacementSpec.BLOCK_FULL,
        polygon=_poly_points(poly_flood),
        bbox=_bbox(poly_flood),
        affected_road=flood_seg.id,
    )

    # T2: Debris near-miss decoy beside a road in NE (synthetic_camera_2)
    ne_roads = [s for s in scene.road_segments if s.zone.value == "NE"]
    debris_seg = ne_roads[0] if ne_roads else scene.road_segments[1]
    poly_debris = _place_near_miss(debris_seg, rng, HazardType.DEBRIS, roads_buffered=roads_buffered)
    h_debris = Hazard(
        id="H-002",
        type=HazardType.DEBRIS,
        placement=PlacementSpec.NEAR_MISS_DECOY,
        polygon=_poly_points(poly_debris),
        bbox=_bbox(poly_debris),
        affected_road=debris_seg.id,
    )

    scene.hazards = [h_flood, h_debris]

    # Compute ground truth
    gt = compute_ground_truth(scene)

    # Render base city images
    plain_path, _labelled_path = render_scene(scene, output_dir, apply_hard_effects=False)

    # Generate 4 quadrant camera images from plain view
    full_img = Image.open(plain_path)
    cx = scene.image_width // 2
    cy = scene.image_height // 2

    cam_crops = {
        "synthetic_camera_1": (0, 0, cx, cy),
        "synthetic_camera_2": (cx, 0, scene.image_width, cy),
        "synthetic_camera_3": (0, cy, cx, scene.image_height),
        "synthetic_camera_4": (cx, cy, scene.image_width, scene.image_height),
    }

    for cam_id, box in cam_crops.items():
        cropped = full_img.crop(box)
        cam_num = cam_id.split("_")[-1]
        crop_path = os.path.join(output_dir, f"camera_{cam_num}.png")
        cropped.save(crop_path, "PNG")

    # Render T3 receded image for camera 1 (flood receded)
    scene_t3 = scene.model_copy(deep=True)
    scene_t3.hazards = [h_debris]  # flood removed
    temp_dir = os.path.join(output_dir, "_temp_t3")
    os.makedirs(temp_dir, exist_ok=True)
    t3_plain, _ = render_scene(scene_t3, temp_dir, apply_hard_effects=False)
    t3_full = Image.open(t3_plain)
    t3_cam1 = t3_full.crop(cam_crops["synthetic_camera_1"])
    t3_cam1.save(os.path.join(output_dir, "camera_1_t3.png"), "PNG")
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)

    # Camera views
    cameras = _make_camera_views(scene)

    # T0–T3 timeline events
    events = [
        {
            "time_step": "T0",
            "timestamp": None,
            "description": "No observations. All roads UNKNOWN.",
            "observations": [],
        },
        {
            "time_step": "T1",
            "timestamp": "2026-11-27T08:00:00+05:30",
            "description": (
                f"Flood detected across {flood_seg.id}. "
                "Expected outcome: BLOCKED. Saved route raises an alert."
            ),
            "observations": [
                {
                    "source": "synthetic_camera_1",
                    "capture_time": "2026-11-27T08:00:00+05:30",
                    "zone": "NW",
                    "affected_segments": [flood_seg.id],
                    "hazard_type": "flood",
                    "image": "camera_1.png",
                },
            ],
        },
        {
            "time_step": "T2",
            "timestamp": "2026-11-27T09:00:00+05:30",
            "description": (
                f"Debris detected beside {debris_seg.id} (near-miss). "
                "Expected outcome: road remains unblocked (CLEAR). No false block."
            ),
            "observations": [
                {
                    "source": "synthetic_camera_2",
                    "capture_time": "2026-11-27T09:00:00+05:30",
                    "zone": "NE",
                    "affected_segments": [debris_seg.id],
                    "hazard_type": "debris",
                    "near_miss": True,
                    "image": "camera_2.png",
                },
            ],
        },
        {
            "time_step": "T3",
            "timestamp": "2026-11-27T10:00:00+05:30",
            "description": (
                f"Same NW corridor ({flood_seg.id}) re-observed with flood receded. "
                "Recovery requires stronger evidence. Status initially UNCERTAIN."
            ),
            "observations": [
                {
                    "source": "synthetic_camera_1",
                    "capture_time": "2026-11-27T10:00:00+05:30",
                    "zone": "NW",
                    "affected_segments": [flood_seg.id],
                    "hazard_type": None,
                    "recovery": True,
                    "image": "camera_1_t3.png",
                },
            ],
        },
    ]

    # Build scenario JSON
    scenario = {
        "scenario_id": "demo_city",
        "description": (
            "DisasterLens demonstration city — a 6×6 grid with four camera views "
            "and a T0–T3 disaster timeline. Results are based on synthetic scenes "
            "and do not establish real-world disaster performance."
        ),
        "grid_size": 6,
        "seed": DEMO_SEED,
        "cameras": cameras,
        "events": events,
        "scene_file": "scene.json",
        "ground_truth_file": "ground_truth.json",
    }

    # Write files with explicit LF line endings for cross-platform determinism
    with open(os.path.join(output_dir, "scenario.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(scenario, f, indent=2, sort_keys=True, ensure_ascii=False)

    with open(os.path.join(output_dir, "scene.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(scene.model_dump(mode="json"), f, indent=2, sort_keys=True, ensure_ascii=False)

    with open(os.path.join(output_dir, "ground_truth.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(gt.model_dump(mode="json"), f, indent=2, sort_keys=True, ensure_ascii=False)

    print(f"Demo city scenario written to {output_dir}/")
    print(f"  Cameras: {len(cameras)}")
    print(f"  Events:  {len(events)}")
    print(f"  Hazards: {len(scene.hazards)}")
    return scenario


if __name__ == "__main__":
    build_demo_city()

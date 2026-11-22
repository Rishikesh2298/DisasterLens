"""
Demo city scenario pack.

Generates a 6×6 city with four camera views (one per quadrant) and
T0–T3 events for the ScenarioPlayer.
"""

from __future__ import annotations

import json
import os
import random as _random

from dl.contracts.scene import Difficulty, HazardType, PlacementSpec, Severity
from dl.generator.city import generate_city
from dl.generator.ground_truth import compute_ground_truth
from dl.generator.hazards import (
    HazardPlan, generate_hazards, _place_block_full, _place_near_miss,
    _place_block_partial, _poly_points, _bbox,
)
from dl.generator.render import render_scene
from dl.contracts.scene import Hazard, BBox, Point


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

    rng = _random.Random(DEMO_SEED)

    # Generate a 6×6 city
    scene = generate_city("DEMO-001", DEMO_SEED, Difficulty.HARD)

    # Place specific hazards for the T0–T3 timeline
    hazards = generate_hazards(scene, rng)
    scene.hazards = hazards

    # Compute ground truth
    gt = compute_ground_truth(scene)

    # Render images
    plain_path, labelled_path = render_scene(scene, output_dir, apply_hard_effects=False)

    # Generate 4 quadrant camera images from plain view
    from PIL import Image
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

    # Camera views
    cameras = _make_camera_views(scene)

    # Identify specific segments for the demo events
    nw_segs = [s.id for s in scene.road_segments if s.zone.value == "NW"]
    ne_segs = [s.id for s in scene.road_segments if s.zone.value == "NE"]

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
                "Flood detected across a main road segment. "
                "Expected: BLOCKED. Route alert should trigger."
            ),
            "observations": [
                {
                    "source": "synthetic_camera_1",
                    "capture_time": "2026-11-27T08:00:00+05:30",
                    "zone": "NW",
                    "affected_segments": nw_segs[:2] if len(nw_segs) >= 2 else nw_segs,
                    "hazard_type": "flood",
                    "image": "camera_1.png",
                },
            ],
        },
        {
            "time_step": "T2",
            "timestamp": "2026-11-27T09:00:00+05:30",
            "description": (
                "Debris detected beside a road (near-miss). "
                "Expected: road remains unblocked. No false-block."
            ),
            "observations": [
                {
                    "source": "synthetic_camera_2",
                    "capture_time": "2026-11-27T09:00:00+05:30",
                    "zone": "NE",
                    "affected_segments": ne_segs[:1] if ne_segs else [],
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
                "Same flood-affected area re-observed with flood receded. "
                "Recovery needs stronger evidence. Status may become UNCERTAIN."
            ),
            "observations": [
                {
                    "source": "synthetic_camera_1",
                    "capture_time": "2026-11-27T10:00:00+05:30",
                    "zone": "NW",
                    "affected_segments": nw_segs[:2] if len(nw_segs) >= 2 else nw_segs,
                    "hazard_type": None,
                    "recovery": True,
                    "image": "camera_1.png",
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

    # Write files
    with open(os.path.join(output_dir, "scenario.json"), "w", encoding="utf-8") as f:
        json.dump(scenario, f, indent=2, sort_keys=True, ensure_ascii=False)

    with open(os.path.join(output_dir, "scene.json"), "w", encoding="utf-8") as f:
        json.dump(scene.model_dump(mode="json"), f, indent=2, sort_keys=True, ensure_ascii=False)

    with open(os.path.join(output_dir, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump(gt.model_dump(mode="json"), f, indent=2, sort_keys=True, ensure_ascii=False)

    print(f"Demo city scenario written to {output_dir}/")
    print(f"  Cameras: {len(cameras)}")
    print(f"  Events:  {len(events)}")
    print(f"  Hazards: {len(scene.hazards)}")
    return scenario


if __name__ == "__main__":
    build_demo_city()

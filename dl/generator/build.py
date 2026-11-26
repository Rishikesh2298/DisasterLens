"""
Dataset build pipeline.

Usage:
    python -m dl.generator.build --n 100 --seed 2026

Generates:
  datasets/v1/
    manifest.json
    stats.json
    S-0001/ … S-0100/
      scene.json
      image_plain.png
      image_labelled.png
      ground_truth.json
      questions.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random as _random
import sys
import time
from pathlib import Path

from dl.contracts.evaluation import EvaluationDatasetScene
from dl.generator.city import generate_city
from dl.generator.ground_truth import compute_ground_truth
from dl.generator.hazards import generate_hazards
from dl.generator.models import (
    Difficulty,
    QuestionType,
    RoadStatus,
    to_contract_scene,
    to_evaluation_record,
)
from dl.generator.questions import generate_questions
from dl.generator.render import render_scene
from dl.generator.validate import validate_scene

# ── Difficulty assignment ─────────────────────────────────────────────────

def _assign_difficulties(n: int) -> list[Difficulty]:
    """Assign 30 easy, 35 medium, 35 hard (for n=100)."""
    if n == 100:
        return (
            [Difficulty.EASY] * 30
            + [Difficulty.MEDIUM] * 35
            + [Difficulty.HARD] * 35
        )
    # For other sizes, distribute proportionally
    n_easy = max(1, int(n * 0.30))
    n_medium = max(1, int(n * 0.35))
    n_hard = n - n_easy - n_medium
    return (
        [Difficulty.EASY] * n_easy
        + [Difficulty.MEDIUM] * n_medium
        + [Difficulty.HARD] * n_hard
    )


def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_json(obj: dict) -> str:
    """Canonical JSON: sorted keys, no trailing whitespace."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)


# ── Build ─────────────────────────────────────────────────────────────────

def build_dataset(
    n: int = 100,
    base_seed: int = 2026,
    output_root: str = "datasets/v1",
    validate: bool = True,
) -> dict:
    """Build the full dataset. Returns stats dict."""
    start_time = time.time()
    output_root = str(Path(output_root).resolve())
    os.makedirs(output_root, exist_ok=True)

    difficulties = _assign_difficulties(n)
    manifest_entries: list[dict] = []
    all_errors: list[str] = []

    # Stats accumulators
    stats = {
        "total_scenes": n,
        "difficulty_counts": {"easy": 0, "medium": 0, "hard": 0},
        "hazard_type_counts": {},
        "road_status_counts": {
            RoadStatus.BLOCKED.value: 0,
            RoadStatus.PARTIAL.value: 0,
            RoadStatus.CLEAR.value: 0,
        },
        "question_type_counts": {},
        "near_miss_route_questions": 0,
        "total_route_questions": 0,
        "placement_spec_counts": {},
    }

    print(f"Building {n} scenes with base seed {base_seed}...")
    print(f"Output: {output_root}")
    print()

    for i in range(n):
        scene_num = i + 1
        scene_id = f"S-{scene_num:04d}"
        seed = base_seed + i
        difficulty = difficulties[i]

        if scene_num % 10 == 0 or scene_num == 1:
            print(f"  [{scene_num:3d}/{n}] {scene_id} ({difficulty.value})...")

        # Scene directory
        scene_dir = os.path.join(output_root, scene_id)
        os.makedirs(scene_dir, exist_ok=True)

        # Deterministic RNG for this scene
        rng = _random.Random(seed)

        # 1. Generate city
        scene = generate_city(scene_id, seed, difficulty)

        # 2. Generate hazards
        hazards = generate_hazards(scene, rng)
        scene.hazards = hazards

        # 3. Compute ground truth
        gt = compute_ground_truth(scene)

        # 4. Generate questions
        qs = generate_questions(scene, gt, rng)

        # 5. Render images
        apply_hard = difficulty == Difficulty.HARD
        render_scene(scene, scene_dir, apply_hard_effects=apply_hard)

        # 6. Write JSON files
        scene_path = os.path.join(scene_dir, "scene.json")
        gt_path = os.path.join(scene_dir, "ground_truth.json")
        q_path = os.path.join(scene_dir, "questions.json")

        with open(scene_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_canonical_json(scene.model_dump(mode="json")))
        with open(gt_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_canonical_json(gt.model_dump(mode="json")))
        with open(q_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_canonical_json(qs.model_dump(mode="json")))

        # 7. Validate
        split = "dev" if scene_num <= 30 else "test"
        if validate:
            errors = validate_scene(scene, gt, scene_dir)
            # Validate canonical shared contracts
            to_contract_scene(scene, gt, qs, split=split)
            EvaluationDatasetScene.model_validate(
                to_evaluation_record(scene, gt, qs, split=split)
            )
            if errors:
                all_errors.extend(errors)
                print(f"    ⚠ {scene_id}: {len(errors)} validation error(s)")
                for e in errors:
                    print(f"      {e}")

        # 8. Update stats
        stats["difficulty_counts"][difficulty.value] += 1

        for h in hazards:
            ht = h.type.value
            stats["hazard_type_counts"][ht] = stats["hazard_type_counts"].get(ht, 0) + 1
            ps = h.placement.value
            stats["placement_spec_counts"][ps] = stats["placement_spec_counts"].get(ps, 0) + 1

        for sgt in gt.segment_statuses:
            stats["road_status_counts"][sgt.status.value] = (
                stats["road_status_counts"].get(sgt.status.value, 0) + 1
            )

        for q in qs.questions:
            qt = q.type.value
            stats["question_type_counts"][qt] = stats["question_type_counts"].get(qt, 0) + 1
            if q.type in (
                QuestionType.ROUTE_OBSTRUCTION_POSITIVE,
                QuestionType.ROUTE_OBSTRUCTION_NEGATIVE,
            ):
                stats["total_route_questions"] += 1
            if q.type == QuestionType.ROUTE_OBSTRUCTION_NEGATIVE:
                stats["near_miss_route_questions"] += 1

        # 9. Manifest entry
        file_hashes = {}
        for fname in ["scene.json", "image_plain.png", "image_labelled.png",
                       "ground_truth.json", "questions.json"]:
            fpath = os.path.join(scene_dir, fname)
            if os.path.exists(fpath):
                file_hashes[fname] = _sha256(fpath)

        manifest_entries.append({
            "scene_id": scene_id,
            "difficulty": difficulty.value,
            "split": split,
            "seed": seed,
            "file_hashes": file_hashes,
        })

    # Near-miss percentage
    if stats["total_route_questions"] > 0:
        stats["near_miss_percentage"] = round(
            100.0 * stats["near_miss_route_questions"] / stats["total_route_questions"], 1
        )
    else:
        stats["near_miss_percentage"] = 0.0

    # Write manifest
    manifest = {"scenes": manifest_entries}
    manifest_path = os.path.join(output_root, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_canonical_json(manifest))

    # Write stats
    stats_path = os.path.join(output_root, "stats.json")
    with open(stats_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_canonical_json(stats))

    elapsed = time.time() - start_time

    # Print report
    print()
    print("=" * 60)
    print("BUILD REPORT")
    print("=" * 60)
    print(f"Scenes generated:    {n}")
    print(f"Difficulties:        {stats['difficulty_counts']}")
    print(f"Hazard types:        {stats['hazard_type_counts']}")
    print(f"Placement specs:     {stats['placement_spec_counts']}")
    print(f"Road statuses:       {stats['road_status_counts']}")
    print(f"Question types:      {stats['question_type_counts']}")
    print(f"Near-miss %:         {stats['near_miss_percentage']}%")
    print(f"Validation errors:   {len(all_errors)}")
    print(f"Time:                {elapsed:.1f}s")
    print(f"Output:              {output_root}")
    print("=" * 60)

    if all_errors:
        print(f"\n⚠ BUILD COMPLETED WITH {len(all_errors)} VALIDATION ERROR(S)")
        print("Dataset may contain incorrect ground truth.")
        # Fail the build
        sys.exit(1)
    else:
        print("\n✓ BUILD PASSED — all scenes validated successfully")

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build the DisasterLens synthetic dataset",
    )
    parser.add_argument("--n", type=int, default=100, help="Number of scenes")
    parser.add_argument("--seed", type=int, default=2026, help="Base seed")
    parser.add_argument("--output", type=str, default="datasets/v1", help="Output directory")
    parser.add_argument("--no-validate", action="store_true", help="Skip validation")
    args = parser.parse_args()

    build_dataset(
        n=args.n,
        base_seed=args.seed,
        output_root=args.output,
        validate=not args.no_validate,
    )


if __name__ == "__main__":
    main()

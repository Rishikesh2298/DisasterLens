"""
Benchmark question generator.

Generates six question types per scene:
  1. blocked_segments       — Which road segments are blocked?
  2. damaged_buildings      — How many buildings are visibly damaged?
  3. water_regions          — Locate regions with standing water.
  4. route_obstruction_pos  — Is route A→B obstructed? (yes)
  5. route_obstruction_neg  — Is route A→B obstructed? (near-miss negative)
  6. zone_comparison        — Which zone has more visible hazard area?

All answers are derived from ground truth. Hidden answers are stored separately
from model-visible prompts.
"""

from __future__ import annotations

import random as _random
from collections import defaultdict
from typing import Optional

from dl.contracts.scene import (
    GroundTruth, Question, QuestionSet, QuestionType, RoadStatus, Scene, Zone,
)


def _build_adjacency(scene: Scene) -> dict[str, list[tuple[str, str]]]:
    """Build adjacency list: node_id → [(neighbour_id, seg_id), ...]."""
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for seg in scene.road_segments:
        adj[seg.node_a].append((seg.node_b, seg.id))
        adj[seg.node_b].append((seg.node_a, seg.id))
    return adj


def _find_path(
    adj: dict[str, list[tuple[str, str]]],
    start: str,
    end: str,
) -> Optional[list[str]]:
    """BFS to find a path; returns list of segment IDs or None."""
    if start == end:
        return []
    visited = {start}
    queue = [(start, [])]
    while queue:
        node, path = queue.pop(0)
        for nbr, seg_id in adj[node]:
            if nbr in visited:
                continue
            new_path = path + [seg_id]
            if nbr == end:
                return new_path
            visited.add(nbr)
            queue.append((nbr, new_path))
    return None


def _seg_status_lookup(gt: GroundTruth) -> dict[str, RoadStatus]:
    return {s.segment_id: s.status for s in gt.segment_statuses}


def generate_questions(
    scene: Scene,
    gt: GroundTruth,
    rng: _random.Random,
) -> QuestionSet:
    """Generate benchmark questions for a scene."""
    questions: list[Question] = []
    q_counter = 1
    adj = _build_adjacency(scene)
    statuses = _seg_status_lookup(gt)
    node_ids = [n.id for n in scene.intersections]

    # ── Q1: Blocked segments ──────────────────────────────────────────────
    blocked = [s.segment_id for s in gt.segment_statuses if s.status == RoadStatus.BLOCKED]
    questions.append(Question(
        id=f"Q-{q_counter:03d}",
        type=QuestionType.BLOCKED_SEGMENTS,
        prompt="Which road segments are blocked in this scene?",
        expected_answer={"blocked_segments": blocked},
    ))
    q_counter += 1

    # ── Q2: Damaged buildings ─────────────────────────────────────────────
    questions.append(Question(
        id=f"Q-{q_counter:03d}",
        type=QuestionType.DAMAGED_BUILDINGS,
        prompt="How many buildings are visibly damaged in this scene?",
        expected_answer={
            "count": len(gt.damaged_building_ids),
            "building_ids": gt.damaged_building_ids,
        },
    ))
    q_counter += 1

    # ── Q3: Water regions ─────────────────────────────────────────────────
    water_bboxes = []
    for h in scene.hazards:
        if h.id in gt.water_region_ids:
            water_bboxes.append({
                "hazard_id": h.id,
                "bbox": {
                    "x_min": h.bbox.x_min,
                    "y_min": h.bbox.y_min,
                    "x_max": h.bbox.x_max,
                    "y_max": h.bbox.y_max,
                },
            })
    questions.append(Question(
        id=f"Q-{q_counter:03d}",
        type=QuestionType.WATER_REGIONS,
        prompt="Locate all regions with standing water in this scene.",
        expected_answer={"water_regions": water_bboxes},
    ))
    q_counter += 1

    # ── Q4: Route obstruction — positive ──────────────────────────────────
    # Find a route that actually passes through a blocked segment
    positive_found = False
    rng_nodes = list(node_ids)
    rng.shuffle(rng_nodes)
    for start in rng_nodes:
        if positive_found:
            break
        for end in rng_nodes:
            if start == end:
                continue
            path = _find_path(adj, start, end)
            if path is None:
                continue
            blocking = [s for s in path if statuses.get(s) == RoadStatus.BLOCKED]
            if blocking:
                questions.append(Question(
                    id=f"Q-{q_counter:03d}",
                    type=QuestionType.ROUTE_OBSTRUCTION_POSITIVE,
                    prompt=(
                        f"Is the route from {start} to {end} obstructed? "
                        "If yes, identify the blocking road segments."
                    ),
                    expected_answer={
                        "obstructed": True,
                        "route_segments": path,
                        "blocking_segments": blocking,
                    },
                ))
                q_counter += 1
                positive_found = True
                break

    # If no blocked route found, still add a placeholder
    if not positive_found and len(node_ids) >= 2:
        s, e = node_ids[0], node_ids[-1]
        path = _find_path(adj, s, e) or []
        questions.append(Question(
            id=f"Q-{q_counter:03d}",
            type=QuestionType.ROUTE_OBSTRUCTION_POSITIVE,
            prompt=(
                f"Is the route from {s} to {e} obstructed? "
                "If yes, identify the blocking road segments."
            ),
            expected_answer={
                "obstructed": False,
                "route_segments": path,
                "blocking_segments": [],
            },
        ))
        q_counter += 1

    # ── Q5: Route obstruction — near-miss negative ────────────────────────
    # Find a route that passes near hazards but is NOT blocked
    negative_found = False
    # Identify segments that have near-miss hazards
    near_miss_segs = set()
    for h in scene.hazards:
        if h.placement and h.placement.value == "near_miss_decoy" and h.affected_road:
            near_miss_segs.add(h.affected_road)

    rng.shuffle(rng_nodes)
    for start in rng_nodes:
        if negative_found:
            break
        for end in rng_nodes:
            if start == end:
                continue
            path = _find_path(adj, start, end)
            if path is None:
                continue
            has_near_miss = any(s in near_miss_segs for s in path)
            all_clear = all(
                statuses.get(s) in (RoadStatus.CLEAR, None) for s in path
            )
            if has_near_miss and all_clear:
                questions.append(Question(
                    id=f"Q-{q_counter:03d}",
                    type=QuestionType.ROUTE_OBSTRUCTION_NEGATIVE,
                    prompt=(
                        f"Is the route from {start} to {end} obstructed? "
                        "If yes, identify the blocking road segments. "
                        "Note: a hazard near a road does not necessarily block it."
                    ),
                    expected_answer={
                        "obstructed": False,
                        "route_segments": path,
                        "blocking_segments": [],
                        "near_miss_hazards": sorted(near_miss_segs & set(path)),
                    },
                ))
                q_counter += 1
                negative_found = True
                break

    # Fallback: any unblocked route
    if not negative_found and len(node_ids) >= 2:
        for start in rng_nodes[:5]:
            if negative_found:
                break
            for end in rng_nodes[-5:]:
                if start == end:
                    continue
                path = _find_path(adj, start, end)
                if path is None:
                    continue
                all_clear = all(
                    statuses.get(s) in (RoadStatus.CLEAR, None) for s in path
                )
                if all_clear:
                    questions.append(Question(
                        id=f"Q-{q_counter:03d}",
                        type=QuestionType.ROUTE_OBSTRUCTION_NEGATIVE,
                        prompt=(
                            f"Is the route from {start} to {end} obstructed? "
                            "If yes, identify the blocking road segments."
                        ),
                        expected_answer={
                            "obstructed": False,
                            "route_segments": path,
                            "blocking_segments": [],
                        },
                    ))
                    q_counter += 1
                    negative_found = True
                    break

    # ── Q6: Zone comparison ───────────────────────────────────────────────
    zone_areas = gt.hazard_area_per_zone
    zones_sorted = sorted(zone_areas.items(), key=lambda x: x[1], reverse=True)
    # Pick two zones with different areas (exclude ties)
    zone_a: Optional[str] = None
    zone_b: Optional[str] = None
    for i in range(len(zones_sorted)):
        for j in range(i + 1, len(zones_sorted)):
            if abs(zones_sorted[i][1] - zones_sorted[j][1]) > 1.0:
                zone_a = zones_sorted[i][0]
                zone_b = zones_sorted[j][0]
                break
        if zone_a:
            break

    if zone_a and zone_b:
        questions.append(Question(
            id=f"Q-{q_counter:03d}",
            type=QuestionType.ZONE_COMPARISON,
            prompt=(
                f"Which zone has more visible hazard area: {zone_a} or {zone_b}?"
            ),
            expected_answer={
                "zone_with_more": zone_a,
                "zone_a": zone_a,
                "zone_a_area": zone_areas[zone_a],
                "zone_b": zone_b,
                "zone_b_area": zone_areas[zone_b],
            },
        ))
        q_counter += 1

    return QuestionSet(scene_id=scene.scene_id, questions=questions)

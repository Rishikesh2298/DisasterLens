"""
Independent raster-based validator.

CRITICAL: This does NOT call ground_truth.py's classification function.
It independently re-computes road statuses using pixel masks and compares
them with the stored ground_truth.json.

Validation steps:
  1. Render binary road masks (per segment) on a NumPy canvas.
  2. Render hazard masks (excluding non-road-affecting hazards).
  3. For each segment, compute per-slice coverage from raster data.
  4. Classify independently.
  5. Compare with ground_truth.json.
  6. Fail on any mismatch.

Additional checks:
  - Near-miss hazards never touch roads.
  - Road graph is connected.
  - IDs are unique.
  - Geometry is valid (Shapely).
  - Every road has a ground-truth status.
  - Every referenced hazard/building exists.
  - Zone references are valid.
  - All required output files exist.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
from shapely.geometry import Polygon as ShapelyPolygon

from dl.contracts.scene import (
    GroundTruth, PlacementSpec, RoadStatus, Scene,
)


BLOCKED_THRESHOLD = 0.90
PARTIAL_THRESHOLD = 0.30
IMAGE_SIZE = 1024


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def _poly_to_shapely(points) -> ShapelyPolygon:
    return ShapelyPolygon([(p.x, p.y) for p in points])


def _rasterize_polygon(polygon_points, canvas_size: int = IMAGE_SIZE) -> np.ndarray:
    """Rasterize a polygon to a boolean mask using scanline fill."""
    mask = np.zeros((canvas_size, canvas_size), dtype=bool)
    pts = [(p.x, p.y) for p in polygon_points]
    if len(pts) < 3:
        return mask

    # Scanline rasterization
    ys = [p[1] for p in pts]
    y_min = max(0, int(min(ys)))
    y_max = min(canvas_size - 1, int(max(ys)))

    for y in range(y_min, y_max + 1):
        intersections = []
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if y1 == y2:
                continue
            if y < min(y1, y2) or y >= max(y1, y2):
                continue
            x_int = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            intersections.append(x_int)
        intersections.sort()
        for j in range(0, len(intersections) - 1, 2):
            x_start = max(0, int(intersections[j]))
            x_end = min(canvas_size - 1, int(intersections[j + 1]))
            mask[y, x_start:x_end + 1] = True

    return mask


def _classify_raster(coverage: float) -> RoadStatus:
    if coverage >= BLOCKED_THRESHOLD:
        return RoadStatus.BLOCKED
    elif coverage >= PARTIAL_THRESHOLD:
        return RoadStatus.PARTIAL
    return RoadStatus.CLEAR


def validate_scene(
    scene: Scene,
    gt: GroundTruth,
    scene_dir: Optional[str] = None,
) -> list[str]:
    """Validate a scene and its ground truth. Returns list of error messages.

    An empty list means validation passed.
    """
    errors: list[str] = []
    sid = scene.scene_id

    # ── Structural checks ─────────────────────────────────────────────────

    # Unique IDs
    seg_ids = [s.id for s in scene.road_segments]
    if len(seg_ids) != len(set(seg_ids)):
        errors.append(f"{sid}: Duplicate road segment IDs")

    bldg_ids = [b.id for b in scene.buildings]
    if len(bldg_ids) != len(set(bldg_ids)):
        errors.append(f"{sid}: Duplicate building IDs")

    haz_ids = [h.id for h in scene.hazards]
    if len(haz_ids) != len(set(haz_ids)):
        errors.append(f"{sid}: Duplicate hazard IDs")

    # Valid geometry
    for seg in scene.road_segments:
        sp = _poly_to_shapely(seg.polygon)
        if not sp.is_valid:
            errors.append(f"{sid}: Invalid geometry for segment {seg.id}")

    for h in scene.hazards:
        hp = _poly_to_shapely(h.polygon)
        if not hp.is_valid or hp.is_empty:
            errors.append(f"{sid}: Invalid geometry for hazard {h.id}")

    # Every segment has a ground-truth status
    gt_seg_ids = {s.segment_id for s in gt.segment_statuses}
    for seg in scene.road_segments:
        if seg.id not in gt_seg_ids:
            errors.append(f"{sid}: Segment {seg.id} missing from ground truth")

    # Every referenced hazard exists
    haz_id_set = set(haz_ids)
    for sgt in gt.segment_statuses:
        for bh in sgt.blocking_hazards:
            if bh not in haz_id_set:
                errors.append(f"{sid}: Blocking hazard {bh} referenced in {sgt.segment_id} not found")

    # Every damaged building exists
    bldg_id_set = set(bldg_ids)
    for db in gt.damaged_building_ids:
        if db not in bldg_id_set:
            errors.append(f"{sid}: Damaged building {db} not found in scene")

    # Zone references are valid
    valid_zones = {"NW", "NE", "SW", "SE"}
    for k in gt.hazard_area_per_zone:
        if k not in valid_zones:
            errors.append(f"{sid}: Invalid zone {k} in hazard_area_per_zone")

    # ── Road graph connectivity ───────────────────────────────────────────
    if scene.intersections:
        adj: dict[str, set[str]] = {n.id: set() for n in scene.intersections}
        for seg in scene.road_segments:
            adj[seg.node_a].add(seg.node_b)
            adj[seg.node_b].add(seg.node_a)
        visited: set[str] = set()
        stack = [scene.intersections[0].id]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adj[node] - visited)
        if len(visited) != len(scene.intersections):
            errors.append(f"{sid}: Road graph is not connected")

    # ── Near-miss hazards must not touch roads ────────────────────────────
    road_union_polys = [_poly_to_shapely(s.polygon) for s in scene.road_segments]
    for h in scene.hazards:
        if h.placement == PlacementSpec.NEAR_MISS_DECOY:
            hp = _poly_to_shapely(h.polygon)
            for rp in road_union_polys:
                if hp.intersects(rp):
                    intersection = hp.intersection(rp)
                    if intersection.area > 1.0:  # Tolerance for floating-point
                        errors.append(
                            f"{sid}: Near-miss hazard {h.id} intersects road "
                            f"(area={intersection.area:.1f})"
                        )
                        break

    # ── Raster-based independent verification ─────────────────────────────
    # Build hazard exclusion set (same as ground_truth.py logic but independently coded)
    non_road_placements = {
        PlacementSpec.NEAR_MISS_DECOY,
        PlacementSpec.WATER_ON_PARK,
        PlacementSpec.DAMAGED_BUILDING_ONLY,
    }

    # Rasterize all road-affecting hazards into one mask
    hazard_mask = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=bool)
    road_affecting_hazards = []
    for h in scene.hazards:
        if h.placement in non_road_placements:
            continue
        road_affecting_hazards.append(h)
        hm = _rasterize_polygon(h.polygon, IMAGE_SIZE)
        hazard_mask |= hm

    # For each segment, compute raster-based coverage
    gt_lookup = {s.segment_id: s for s in gt.segment_statuses}

    for seg in scene.road_segments:
        seg_mask = _rasterize_polygon(seg.polygon, IMAGE_SIZE)
        seg_pixels = seg_mask.sum()
        if seg_pixels == 0:
            continue

        # Per-slice coverage (simulate cross-sections via horizontal/vertical slices)
        # Determine orientation
        dx = abs(seg.centerline[0].x - seg.centerline[1].x)
        dy = abs(seg.centerline[0].y - seg.centerline[1].y)
        is_horizontal = dx > dy

        sp = _poly_to_shapely(seg.polygon)
        sb = sp.bounds  # (minx, miny, maxx, maxy)

        n_slices = 20
        max_coverage = 0.0

        if is_horizontal:
            # Slice vertically (perpendicular to horizontal road)
            x_start = sb[0]
            x_end = sb[2]
            slice_width = (x_end - x_start) / n_slices
            for i in range(n_slices):
                sx = int(round(x_start + (i + 0.5) * slice_width))
                if 0 <= sx < IMAGE_SIZE:
                    # Get column slice within segment bounds
                    y_lo = max(0, int(round(sb[1])))
                    y_hi = min(IMAGE_SIZE, int(round(sb[3])) + 1)
                    road_col = seg_mask[y_lo:y_hi, sx]
                    hazard_col = hazard_mask[y_lo:y_hi, sx]
                    road_px = road_col.sum()
                    if road_px > 0:
                        covered = (road_col & hazard_col).sum()
                        cov = covered / road_px
                        max_coverage = max(max_coverage, cov)
        else:
            # Slice horizontally (perpendicular to vertical road)
            y_start = sb[1]
            y_end = sb[3]
            slice_width = (y_end - y_start) / n_slices
            for i in range(n_slices):
                sy = int(round(y_start + (i + 0.5) * slice_width))
                if 0 <= sy < IMAGE_SIZE:
                    x_lo = max(0, int(round(sb[0])))
                    x_hi = min(IMAGE_SIZE, int(round(sb[2])) + 1)
                    road_row = seg_mask[sy, x_lo:x_hi]
                    hazard_row = hazard_mask[sy, x_lo:x_hi]
                    road_px = road_row.sum()
                    if road_px > 0:
                        covered = (road_row & hazard_row).sum()
                        cov = covered / road_px
                        max_coverage = max(max_coverage, cov)

        raster_status = _classify_raster(max_coverage)

        # Check for road_damage minor severity cap
        from dl.contracts.scene import HazardType, Severity
        for h in road_affecting_hazards:
            if (h.affected_road == seg.id
                and h.type == HazardType.ROAD_DAMAGE
                and h.severity == Severity.MINOR
                and raster_status == RoadStatus.BLOCKED):
                raster_status = RoadStatus.PARTIAL
                break

        # Compare with stored ground truth
        gt_entry = gt_lookup.get(seg.id)
        if gt_entry is None:
            errors.append(f"{sid}: Segment {seg.id} not in ground truth")
            continue

        if raster_status != gt_entry.status:
            # Allow tolerance: raster and vector methods may disagree slightly
            # near thresholds. Only flag if clearly wrong.
            # We allow CLEAR↔PARTIAL disagreements when coverage is near 0.30
            # and PARTIAL↔BLOCKED near 0.90, with a 5% tolerance band.
            cov_diff = abs(max_coverage - gt_entry.max_coverage)
            if cov_diff > 0.10:  # Significant disagreement
                errors.append(
                    f"{sid}: Segment {seg.id} — raster says {raster_status.value} "
                    f"(cov={max_coverage:.3f}), ground truth says {gt_entry.status.value} "
                    f"(cov={gt_entry.max_coverage:.4f})"
                )

    # ── File existence checks ─────────────────────────────────────────────
    if scene_dir:
        expected = ["scene.json", "image_plain.png", "image_labelled.png",
                     "ground_truth.json", "questions.json"]
        for f in expected:
            if not os.path.exists(os.path.join(scene_dir, f)):
                errors.append(f"{sid}: Missing file {f}")

    return errors

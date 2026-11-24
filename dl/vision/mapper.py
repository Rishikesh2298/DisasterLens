"""
Hazard-to-road geometric mapper for DisasterLens.

Calculates road obstruction coverage ratios and classifications (BLOCKED, PARTIAL, CLEAR)
independently of raw model verdicts, using Shapely 2 geometric cross-section sampling.

LIMITATION NOTE:
The current shared Hazard/PredictedHazard contracts do not include a road_damage severity
field (extra="forbid" is enforced on models). All road_damage hazards are geometrically
evaluated based on physical intersection coverage without artificial severity weighting.
"""

from __future__ import annotations

import math
from typing import Collection, NamedTuple, Sequence

from shapely import Polygon, LineString, box as shapely_box, unary_union
from shapely.geometry.base import BaseGeometry

from dl.contracts.enums import HazardType, RoadStatus
from dl.contracts.scene import Box, Hazard, RoadSegment
from dl.contracts.vision import PredictedHazard


class RoadMappingResult(NamedTuple):
    """Result of mapping hazards against a road segment."""

    status: RoadStatus
    max_coverage: float


def _box_to_geometry(b: Box) -> Polygon:
    """Convert a Box instance [x1, y1, x2, y2] to a Shapely box polygon."""
    x1, y1, x2, y2 = b.root
    return shapely_box(x1, y1, x2, y2)


def _extract_hazard_geometry(hazard: Hazard | PredictedHazard) -> Polygon | None:
    """
    Extract a valid Shapely polygon for a hazard.

    Damaged buildings alone never cause road blockages.
    For Hazard: uses polygon if valid (>=3 pts), otherwise falls back to bbox.
    For PredictedHazard: uses bbox.
    """
    if hazard.type == HazardType.DAMAGED_BUILDING:
        # Damaged building alone never blocks a road unless combined with other debris
        return None

    if isinstance(hazard, Hazard):
        if hazard.polygon and len(hazard.polygon) >= 3:
            poly = Polygon(hazard.polygon)
            if poly.is_valid and not poly.is_empty and poly.area > 0:
                return poly
        return _box_to_geometry(hazard.bbox)

    if isinstance(hazard, PredictedHazard):
        return _box_to_geometry(hazard.bbox)

    return None


def _combine_hazard_geometries(
    hazards: Collection[Hazard | PredictedHazard],
) -> BaseGeometry | None:
    """
    Combine all non-building hazard shapes into a single union geometry.

    Uses unary_union to prevent overlapping hazards from being double-counted.
    """
    geoms: list[Polygon] = []
    for h in hazards:
        g = _extract_hazard_geometry(h)
        if g is not None and not g.is_empty and g.is_valid:
            geoms.append(g)

    if not geoms:
        return None

    union_geom = unary_union(geoms)
    return union_geom if not union_geom.is_empty else None


def _build_road_polygon(segment: RoadSegment) -> Polygon:
    """Build and validate a road polygon from RoadSegment polygon coordinates."""
    if not segment.polygon or len(segment.polygon) < 3:
        raise ValueError(
            f"Road segment '{segment.segment_id}' does not have a valid polygon (needs >= 3 points)."
        )
    poly = Polygon(segment.polygon)
    if not poly.is_valid or poly.is_empty or poly.area <= 0:
        raise ValueError(
            f"Road segment '{segment.segment_id}' polygon is invalid or has non-positive area."
        )
    return poly


def _build_road_centerline(segment: RoadSegment) -> LineString:
    """Build and validate a road centerline from RoadSegment centerline coordinates."""
    if not segment.centerline or len(segment.centerline) < 2:
        raise ValueError(
            f"Road segment '{segment.segment_id}' centerline must contain at least 2 points."
        )
    line = LineString(segment.centerline)
    if line.is_empty or line.length <= 0:
        raise ValueError(
            f"Road segment '{segment.segment_id}' centerline has zero or invalid length."
        )
    return line


def _generate_cross_sections(
    centerline: LineString,
    road_polygon: Polygon,
    num_sections: int = 20,
) -> list[LineString]:
    """
    Generate perpendicular cross-sections across the road clipped to the road polygon.

    Samples `num_sections` interior positions along the centerline.
    """
    total_length = centerline.length
    # Probe ray length: diagonal of the road polygon's bounding box ensures full traversal
    minx, miny, maxx, maxy = road_polygon.bounds
    diag = math.hypot(maxx - minx, maxy - miny) * 2.0
    if diag <= 0:
        return []

    sections: list[LineString] = []

    # Sample exactly num_sections interior positions: i from 1 to num_sections
    # spacing factor = i / (num_sections + 1)
    for i in range(1, num_sections + 1):
        d = (i / (num_sections + 1)) * total_length
        pt = centerline.interpolate(d)

        # Estimate local direction tangent vector (dx, dy)
        eps = min(total_length * 0.01, 1.0)
        d_before = max(0.0, d - eps)
        d_after = min(total_length, d + eps)
        pt_before = centerline.interpolate(d_before)
        pt_after = centerline.interpolate(d_after)

        dx = pt_after.x - pt_before.x
        dy = pt_after.y - pt_before.y
        norm = math.hypot(dx, dy)
        if norm <= 0:
            continue

        # Perpendicular normal unit vector (-dy, dx)
        nx = -dy / norm
        ny = dx / norm

        # Line extending outwards symmetrically across the road
        ray_p1 = (pt.x + nx * diag, pt.y + ny * diag)
        ray_p2 = (pt.x - nx * diag, pt.y - ny * diag)
        long_cross = LineString([ray_p1, ray_p2])

        # Clip perpendicular line to road polygon boundary
        clipped = long_cross.intersection(road_polygon)
        if clipped.is_empty:
            continue

        # If clipping yields multiple components, pick the line containing or closest to sample point
        if clipped.geom_type == "LineString":
            if clipped.length > 0:
                sections.append(clipped)
        elif clipped.geom_type in ("MultiLineString", "GeometryCollection"):
            best_line: LineString | None = None
            best_dist = float("inf")
            for geom in getattr(clipped, "geoms", []):
                if geom.geom_type == "LineString" and geom.length > 0:
                    dist = geom.distance(pt)
                    if dist < best_dist:
                        best_dist = dist
                        best_line = geom
            if best_line is not None:
                sections.append(best_line)

    return sections


def calculate_segment_coverage(
    segment: RoadSegment,
    hazard_union: BaseGeometry | None,
    num_sections: int = 20,
) -> float:
    """
    Calculate maximum hazard coverage ratio [0.0, 1.0] across all cross-sections of a road segment.

    Coverage at each section = (length of section covered by hazards) / (total road width at that section).
    """
    if hazard_union is None or hazard_union.is_empty:
        return 0.0

    road_poly = _build_road_polygon(segment)
    centerline = _build_road_centerline(segment)

    # Quick bounding box disjoint optimization
    if not road_poly.intersects(hazard_union):
        return 0.0

    cross_sections = _generate_cross_sections(centerline, road_poly, num_sections)
    if not cross_sections:
        return 0.0

    max_cov = 0.0
    for section in cross_sections:
        road_width = section.length
        if road_width <= 0:
            continue

        intersection = section.intersection(hazard_union)
        if intersection.is_empty:
            covered_len = 0.0
        else:
            covered_len = intersection.length

        cov = min(1.0, max(0.0, covered_len / road_width))
        if cov > max_cov:
            max_cov = cov

    return round(max_cov, 4)


def classify_coverage(coverage: float) -> RoadStatus:
    """
    Classify maximum coverage ratio according to DisasterLens rules:
    - >= 0.90 -> BLOCKED
    - 0.30 <= coverage < 0.90 -> PARTIAL
    - < 0.30 -> CLEAR
    """
    if coverage >= 0.90:
        return RoadStatus.BLOCKED
    if coverage >= 0.30:
        return RoadStatus.PARTIAL
    return RoadStatus.CLEAR


def map_hazards_to_roads(
    segments: Collection[RoadSegment],
    hazards: Collection[Hazard | PredictedHazard],
    num_sections: int = 20,
) -> dict[str, RoadMappingResult]:
    """
    Map a collection of hazards to road segments using 20 perpendicular cross-sections.

    Args:
        segments: Collection of RoadSegment contract objects.
        hazards: Collection of Hazard or PredictedHazard objects.
        num_sections: Number of cross-sections to sample along centerline (default: 20).

    Returns:
        Mapping from segment_id to RoadMappingResult(status, max_coverage).
    """
    # 1. First validate all road geometries (raising descriptive ValueError on invalid geometry)
    for seg in segments:
        _ = _build_road_polygon(seg)
        _ = _build_road_centerline(seg)

    # 2. Combine hazards into union to prevent double-counting overlaps
    hazard_union = _combine_hazard_geometries(hazards)

    # 3. Calculate coverage and status for each segment
    results: dict[str, RoadMappingResult] = {}
    for seg in segments:
        coverage = calculate_segment_coverage(seg, hazard_union, num_sections)
        status = classify_coverage(coverage)
        results[seg.segment_id] = RoadMappingResult(status=status, max_coverage=coverage)

    return results

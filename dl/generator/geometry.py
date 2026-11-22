"""
Geometry utilities for DisasterLens ground-truth computation.

Provides cross-section coverage analysis for road segments,
used by both the vector ground-truth engine and the raster validator.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon as ShapelyPolygon
from shapely.ops import unary_union

from dl.contracts.scene import Point, RoadSegment


def _to_shapely(points: list[Point]) -> ShapelyPolygon:
    """Convert list[Point] → Shapely Polygon."""
    return ShapelyPolygon([(p.x, p.y) for p in points])


def segment_centerline(seg: RoadSegment) -> LineString:
    """Return the Shapely LineString for a segment's centerline."""
    return LineString([(p.x, p.y) for p in seg.centerline])


def segment_polygon(seg: RoadSegment) -> ShapelyPolygon:
    """Return the Shapely Polygon for a segment's road area."""
    return _to_shapely(seg.polygon)


def cross_section_coverage(
    seg: RoadSegment,
    hazard_polys: list[ShapelyPolygon],
    n_sections: int = 20,
) -> tuple[float, list[float]]:
    """Compute maximum hazard coverage across *n_sections* perpendicular slices.

    Parameters
    ----------
    seg : The road segment to analyse.
    hazard_polys : List of Shapely hazard polygons relevant to this segment.
    n_sections : Number of equally-spaced cross-sections (default 20).

    Returns
    -------
    (max_coverage, per_section_coverages)
        max_coverage ∈ [0, 1] — the worst-case fraction of road width covered.
        per_section_coverages — coverage at each sampled position.
    """
    cline = segment_centerline(seg)
    road_width = seg.width_px

    if not hazard_polys or cline.length == 0:
        return 0.0, [0.0] * n_sections

    hazard_union = unary_union(hazard_polys)
    if hazard_union.is_empty:
        return 0.0, [0.0] * n_sections

    coverages: list[float] = []
    for i in range(n_sections):
        # Position along the centerline
        frac = (i + 0.5) / n_sections
        pt = cline.interpolate(frac, normalized=True)

        # Direction at this point (tangent)
        eps = 1e-4
        f1 = max(0.0, frac - eps)
        f2 = min(1.0, frac + eps)
        p1 = cline.interpolate(f1, normalized=True)
        p2 = cline.interpolate(f2, normalized=True)
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        length = math.hypot(dx, dy)
        if length < 1e-10:
            coverages.append(0.0)
            continue

        # Perpendicular direction
        nx = -dy / length
        ny = dx / length

        # Cross-section line spanning full road width
        half_w = road_width / 2.0
        cs_start = (pt.x - nx * half_w, pt.y - ny * half_w)
        cs_end = (pt.x + nx * half_w, pt.y + ny * half_w)
        cross_line = LineString([cs_start, cs_end])

        # Intersection with hazard union
        intersection = cross_line.intersection(hazard_union)
        covered_length = intersection.length if not intersection.is_empty else 0.0

        coverage = min(covered_length / road_width, 1.0)
        coverages.append(coverage)

    max_cov = max(coverages) if coverages else 0.0
    return max_cov, coverages

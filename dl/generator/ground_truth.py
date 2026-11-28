"""
Vector-based ground-truth computation.

For every road segment:
  1. Build 20 perpendicular cross-sections along the centerline.
  2. Intersect each with the union of relevant hazard polygons.
  3. Compute the max coverage fraction.
  4. Classify: ≥0.90 → BLOCKED, ≥0.30 → PARTIAL, else CLEAR.

Special rules:
  - damaged_building_only hazards never block roads.
  - road_damage severity: minor → PARTIAL (even if coverage high),
    major → uses standard thresholds.
  - near_miss_decoy hazards are excluded from road coverage.
"""

from __future__ import annotations

from shapely.geometry import Polygon as ShapelyPolygon

from dl.generator.geometry import cross_section_coverage
from dl.generator.models import (
    GroundTruth,
    Hazard,
    HazardType,
    PlacementSpec,
    RoadStatus,
    Scene,
    SegmentGroundTruth,
    Severity,
    Zone,
)

BLOCKED_THRESHOLD = 0.90
PARTIAL_THRESHOLD = 0.30


def _hazard_poly(h: Hazard) -> ShapelyPolygon:
    return ShapelyPolygon([(p.x, p.y) for p in h.polygon])


def _classify(coverage: float) -> RoadStatus:
    if coverage >= BLOCKED_THRESHOLD:
        return RoadStatus.BLOCKED
    elif coverage >= PARTIAL_THRESHOLD:
        return RoadStatus.PARTIAL
    return RoadStatus.CLEAR


def compute_ground_truth(scene: Scene) -> GroundTruth:
    """Compute vector-based ground truth for all road segments."""

    # Pre-filter hazards that can affect roads
    road_hazards: list[Hazard] = []
    for h in scene.hazards:
        # Exclude hazards that never block roads
        if h.placement in (
            PlacementSpec.NEAR_MISS_DECOY,
            PlacementSpec.WATER_ON_PARK,
            PlacementSpec.DAMAGED_BUILDING_ONLY,
        ):
            continue
        road_hazards.append(h)

    # Build Shapely polygons
    hazard_shapely = [(h, _hazard_poly(h)) for h in road_hazards]

    segment_statuses: list[SegmentGroundTruth] = []
    damaged_buildings: set[str] = set()
    water_regions: set[str] = set()
    zone_areas: dict[str, float] = {z.value: 0.0 for z in Zone}

    # Collect damaged buildings and water regions
    for h in scene.hazards:
        if h.placement == PlacementSpec.DAMAGED_BUILDING_ONLY and h.affected_building:
            damaged_buildings.add(h.affected_building)
        if h.placement == PlacementSpec.BUILDING_SPILL and h.affected_building:
            damaged_buildings.add(h.affected_building)
        if h.type == HazardType.FLOOD:
            water_regions.add(h.id)

    # Compute hazard area per zone
    for h in scene.hazards:
        hp = _hazard_poly(h)
        area = hp.area
        # Assign to zone based on centroid
        c = hp.centroid
        cx, cy = scene.image_width / 2, scene.image_height / 2
        if c.x < cx:
            zone = Zone.NW if c.y < cy else Zone.SW
        else:
            zone = Zone.NE if c.y < cy else Zone.SE
        zone_areas[zone.value] += area

    # Compute per-segment status
    for seg in scene.road_segments:
        seg_poly = ShapelyPolygon([(p.x, p.y) for p in seg.polygon])
        relevant_hazards: list[ShapelyPolygon] = []
        blocking_ids: list[str] = []

        for h, hp in hazard_shapely:
            if seg_poly.intersects(hp):
                relevant_hazards.append(hp)
                blocking_ids.append(h.id)

        if relevant_hazards:
            max_cov, _ = cross_section_coverage(seg, relevant_hazards)
        else:
            max_cov = 0.0

        # Apply road_damage severity override
        status = _classify(max_cov)

        # For road_damage with minor severity, cap at PARTIAL
        for h, _ in hazard_shapely:
            if (h.affected_road == seg.id
                and h.type == HazardType.ROAD_DAMAGE
                and h.severity == Severity.MINOR
                and status == RoadStatus.BLOCKED):
                status = RoadStatus.PARTIAL
                break

        # If CLEAR, no blocking hazards
        if status == RoadStatus.CLEAR:
            blocking_ids = []

        segment_statuses.append(SegmentGroundTruth(
            segment_id=seg.id,
            status=status,
            max_coverage=round(max_cov, 4),
            blocking_hazards=blocking_ids,
        ))

    return GroundTruth(
        scene_id=scene.scene_id,
        segment_statuses=segment_statuses,
        damaged_building_ids=sorted(damaged_buildings),
        water_region_ids=sorted(water_regions),
        hazard_area_per_zone={k: round(v, 2) for k, v in zone_areas.items()},
    )

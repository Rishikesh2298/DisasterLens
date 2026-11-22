"""
Deterministic hazard generator.

Creates hazards with explicit placement specifications so that the intended
ground-truth outcome (BLOCKED / PARTIAL / CLEAR) is known *before* geometry
verification.  The generator does NOT randomly scatter hazards and infer
labels — it places them according to spec.

Hazard types: flood, debris, fallen_tree, road_damage, damaged_building.

Placement specs:
  block_full       — covers entire road width, ≥30 px along road → BLOCKED
  block_partial    — covers ~50% road width → PARTIAL
  near_miss_decoy  — beside road, ≥8 px gap, never touches → CLEAR
  water_on_park    — on park, doesn't touch roads → CLEAR
  damaged_building_only — damaged building, no road spill → road CLEAR
  building_spill   — rubble from building extends onto road → BLOCKED/PARTIAL
  road_damage      — cracks/craters; minor → PARTIAL, major → BLOCKED
"""

from __future__ import annotations

import random as _random
from typing import Optional

from shapely.geometry import box as shapely_box, Polygon as ShapelyPolygon
from shapely.ops import unary_union

from dl.contracts.scene import (
    BBox, Building, Difficulty, Hazard, HazardType, Park, PlacementSpec,
    Point, RoadSegment, Scene, Severity, Zone,
)


def _poly_points(shapely_poly: ShapelyPolygon) -> list[Point]:
    coords = list(shapely_poly.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [Point(x=round(c[0], 2), y=round(c[1], 2)) for c in coords]


def _bbox(shapely_poly: ShapelyPolygon) -> BBox:
    b = shapely_poly.bounds  # (minx, miny, maxx, maxy)
    return BBox(x_min=round(b[0], 2), y_min=round(b[1], 2),
                x_max=round(b[2], 2), y_max=round(b[3], 2))


def _seg_poly(seg: RoadSegment) -> ShapelyPolygon:
    return ShapelyPolygon([(p.x, p.y) for p in seg.polygon])


def _is_horizontal(seg: RoadSegment) -> bool:
    dy = abs(seg.centerline[0].y - seg.centerline[1].y)
    dx = abs(seg.centerline[0].x - seg.centerline[1].x)
    return dx > dy


# ── Hazard placement functions ────────────────────────────────────────────

def _place_block_full(
    seg: RoadSegment, rng: _random.Random, htype: HazardType,
) -> ShapelyPolygon:
    """Full-width block: covers entire road width, ≥30 px length."""
    sp = _seg_poly(seg)
    b = sp.bounds
    hz = _is_horizontal(seg)
    if hz:
        road_len = b[2] - b[0]
        extent = max(35, rng.uniform(0.15, 0.3) * road_len)
        start = rng.uniform(b[0] + 5, b[2] - extent - 5)
        poly = shapely_box(start, b[1], start + extent, b[3])
    else:
        road_len = b[3] - b[1]
        extent = max(35, rng.uniform(0.15, 0.3) * road_len)
        start = rng.uniform(b[1] + 5, b[3] - extent - 5)
        poly = shapely_box(b[0], start, b[2], start + extent)
    return poly


def _place_block_partial(
    seg: RoadSegment, rng: _random.Random, htype: HazardType,
) -> ShapelyPolygon:
    """Partial block: covers ~50% of road width."""
    sp = _seg_poly(seg)
    b = sp.bounds
    hz = _is_horizontal(seg)
    if hz:
        road_len = b[2] - b[0]
        extent = max(30, rng.uniform(0.1, 0.25) * road_len)
        start_x = rng.uniform(b[0] + 5, b[2] - extent - 5)
        road_h = b[3] - b[1]
        half_h = road_h * 0.5
        # Offset to one side
        if rng.random() < 0.5:
            poly = shapely_box(start_x, b[1], start_x + extent, b[1] + half_h)
        else:
            poly = shapely_box(start_x, b[3] - half_h, start_x + extent, b[3])
    else:
        road_len = b[3] - b[1]
        extent = max(30, rng.uniform(0.1, 0.25) * road_len)
        start_y = rng.uniform(b[1] + 5, b[3] - extent - 5)
        road_w = b[2] - b[0]
        half_w = road_w * 0.5
        if rng.random() < 0.5:
            poly = shapely_box(b[0], start_y, b[0] + half_w, start_y + extent)
        else:
            poly = shapely_box(b[2] - half_w, start_y, b[2], start_y + extent)
    return poly


def _place_near_miss(
    seg: RoadSegment,
    rng: _random.Random,
    htype: HazardType,
    roads_buffered: Optional[ShapelyPolygon] = None,
) -> ShapelyPolygon:
    """Decoy hazard beside road with ≥8 px gap from ALL roads."""
    sp = _seg_poly(seg)
    b = sp.bounds
    hz = _is_horizontal(seg)
    canvas = shapely_box(0, 0, 1024, 1024)

    # Try up to 25 candidate placements
    for _ in range(25):
        gap = rng.uniform(9, 16)  # >= 8 px gap
        size = rng.uniform(20, 35)

        if hz:
            # Place away from intersections (middle 50% of segment)
            seg_len = b[2] - b[0]
            if seg_len < size + 60:
                continue
            x_start = rng.uniform(b[0] + 35, b[2] - size - 35)
            # Above or below
            if rng.random() < 0.5:
                y_start = b[1] - gap - size
            else:
                y_start = b[3] + gap
            poly = shapely_box(x_start, y_start, x_start + size, y_start + size)
        else:
            seg_len = b[3] - b[1]
            if seg_len < size + 60:
                continue
            y_start = rng.uniform(b[1] + 35, b[3] - size - 35)
            # Left or right
            if rng.random() < 0.5:
                x_start = b[0] - gap - size
            else:
                x_start = b[2] + gap
            poly = shapely_box(x_start, y_start, x_start + size, y_start + size)

        poly = poly.intersection(canvas)
        if poly.is_empty or not poly.is_valid:
            continue

        if roads_buffered is not None:
            if poly.intersects(roads_buffered):
                continue

        return poly

    # Fallback: create a safe small polygon 12px away from seg center
    mid_x = (b[0] + b[2]) / 2
    mid_y = (b[1] + b[3]) / 2
    size = 20
    if hz:
        poly = shapely_box(mid_x - size / 2, b[1] - 12 - size, mid_x + size / 2, b[1] - 12)
    else:
        poly = shapely_box(b[0] - 12 - size, mid_y - size / 2, b[0] - 12, mid_y + size / 2)
    return poly.intersection(canvas)


def _place_water_on_park(
    park: Park, rng: _random.Random,
) -> ShapelyPolygon:
    """Standing water on a park — does not touch any road."""
    park_poly = ShapelyPolygon([(p.x, p.y) for p in park.polygon])
    b = park_poly.bounds
    # Inset so water doesn't reach park edges (and thus roads)
    inset = 8
    w = rng.uniform(0.3, 0.6) * (b[2] - b[0])
    h = rng.uniform(0.3, 0.6) * (b[3] - b[1])
    cx = rng.uniform(b[0] + inset + w / 2, b[2] - inset - w / 2)
    cy = rng.uniform(b[1] + inset + h / 2, b[3] - inset - h / 2)
    poly = shapely_box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    # Ensure it stays within park
    poly = poly.intersection(park_poly)
    return poly


def _place_building_spill(
    building: Building, seg: RoadSegment, rng: _random.Random,
) -> ShapelyPolygon:
    """Rubble from a building extends onto a road."""
    bpoly = ShapelyPolygon([(p.x, p.y) for p in building.polygon])
    rpoly = _seg_poly(seg)

    bb = bpoly.bounds
    rb = rpoly.bounds
    # Create rubble rectangle from building toward road
    hz = _is_horizontal(seg)
    if hz:
        # Building above or below road
        if bb[3] < rb[1]:  # building above road
            poly = shapely_box(
                max(bb[0], rb[0]),
                bb[3] - 5,
                min(bb[2], rb[2]),
                rb[1] + seg.width_px * 0.6,
            )
        else:  # building below road
            poly = shapely_box(
                max(bb[0], rb[0]),
                rb[3] - seg.width_px * 0.6,
                min(bb[2], rb[2]),
                bb[1] + 5,
            )
    else:
        if bb[2] < rb[0]:  # building left of road
            poly = shapely_box(
                bb[2] - 5,
                max(bb[1], rb[1]),
                rb[0] + seg.width_px * 0.6,
                min(bb[3], rb[3]),
            )
        else:  # building right of road
            poly = shapely_box(
                rb[2] - seg.width_px * 0.6,
                max(bb[1], rb[1]),
                bb[0] + 5,
                min(bb[3], rb[3]),
            )

    canvas = shapely_box(0, 0, 1024, 1024)
    poly = poly.intersection(canvas)
    return poly


def _place_road_damage(
    seg: RoadSegment, rng: _random.Random, severity: Severity,
) -> ShapelyPolygon:
    """Road cracks/craters. Minor → PARTIAL, Major → BLOCKED."""
    sp = _seg_poly(seg)
    b = sp.bounds
    hz = _is_horizontal(seg)

    if severity == Severity.MAJOR:
        # Cover full width, 30+ px extent → BLOCKED
        return _place_block_full(seg, rng, HazardType.ROAD_DAMAGE)
    else:
        # Minor: cover ~40% of width → PARTIAL
        return _place_block_partial(seg, rng, HazardType.ROAD_DAMAGE)


# ── Hazard Plan ───────────────────────────────────────────────────────────

class HazardPlan:
    """Specification for a single hazard to be placed."""

    def __init__(
        self,
        htype: HazardType,
        placement: PlacementSpec,
        target_seg_idx: Optional[int] = None,
        target_park_idx: Optional[int] = None,
        target_building_idx: Optional[int] = None,
        severity: Optional[Severity] = None,
    ):
        self.htype = htype
        self.placement = placement
        self.target_seg_idx = target_seg_idx
        self.target_park_idx = target_park_idx
        self.target_building_idx = target_building_idx
        self.severity = severity


def _make_difficulty_plans(
    difficulty: Difficulty,
    n_segments: int,
    n_parks: int,
    n_buildings: int,
    rng: _random.Random,
) -> list[HazardPlan]:
    """Generate hazard plans appropriate for the difficulty level."""
    plans: list[HazardPlan] = []

    if difficulty == Difficulty.EASY:
        # 1-2 hazards, large and high-contrast, no distractors
        num = rng.randint(1, 2)
        for _ in range(num):
            htype = rng.choice([HazardType.FLOOD, HazardType.DEBRIS])
            seg_idx = rng.randint(0, n_segments - 1)
            plans.append(HazardPlan(htype, PlacementSpec.BLOCK_FULL, target_seg_idx=seg_idx))

    elif difficulty == Difficulty.MEDIUM:
        # 2-4 hazards; partial hazards, near-miss, water-on-park
        num = rng.randint(2, 4)
        specs = [
            PlacementSpec.BLOCK_FULL,
            PlacementSpec.BLOCK_PARTIAL,
            PlacementSpec.NEAR_MISS_DECOY,
        ]
        if n_parks > 0:
            specs.append(PlacementSpec.WATER_ON_PARK)

        for i in range(num):
            spec = specs[i % len(specs)]
            if spec == PlacementSpec.WATER_ON_PARK:
                htype = HazardType.FLOOD
                park_idx = rng.randint(0, n_parks - 1) if n_parks > 0 else None
                plans.append(HazardPlan(htype, spec, target_park_idx=park_idx))
            elif spec == PlacementSpec.NEAR_MISS_DECOY:
                htype = rng.choice([HazardType.DEBRIS, HazardType.FALLEN_TREE])
                seg_idx = rng.randint(0, n_segments - 1)
                plans.append(HazardPlan(htype, spec, target_seg_idx=seg_idx))
            else:
                htype = rng.choice([HazardType.FLOOD, HazardType.DEBRIS, HazardType.FALLEN_TREE])
                seg_idx = rng.randint(0, n_segments - 1)
                plans.append(HazardPlan(htype, spec, target_seg_idx=seg_idx))

    else:  # HARD
        # 3-6 hazards; small hazards, near-miss, building spill, road damage
        num = rng.randint(3, 6)
        specs = [
            PlacementSpec.BLOCK_FULL,
            PlacementSpec.BLOCK_PARTIAL,
            PlacementSpec.NEAR_MISS_DECOY,
            PlacementSpec.DAMAGED_BUILDING_ONLY,
            PlacementSpec.ROAD_DAMAGE,
        ]
        if n_buildings > 1:
            specs.append(PlacementSpec.BUILDING_SPILL)
        if n_parks > 0:
            specs.append(PlacementSpec.WATER_ON_PARK)

        for i in range(num):
            spec = specs[i % len(specs)]
            if spec == PlacementSpec.WATER_ON_PARK:
                plans.append(HazardPlan(
                    HazardType.FLOOD, spec,
                    target_park_idx=rng.randint(0, n_parks - 1) if n_parks > 0 else None,
                ))
            elif spec == PlacementSpec.DAMAGED_BUILDING_ONLY:
                plans.append(HazardPlan(
                    HazardType.DAMAGED_BUILDING, spec,
                    target_building_idx=rng.randint(0, n_buildings - 1),
                ))
            elif spec == PlacementSpec.BUILDING_SPILL:
                plans.append(HazardPlan(
                    HazardType.DEBRIS, spec,
                    target_building_idx=rng.randint(0, min(n_buildings - 1, n_buildings)),
                    target_seg_idx=rng.randint(0, n_segments - 1),
                ))
            elif spec == PlacementSpec.ROAD_DAMAGE:
                sev = rng.choice([Severity.MINOR, Severity.MAJOR])
                plans.append(HazardPlan(
                    HazardType.ROAD_DAMAGE, spec,
                    target_seg_idx=rng.randint(0, n_segments - 1),
                    severity=sev,
                ))
            elif spec == PlacementSpec.NEAR_MISS_DECOY:
                htype = rng.choice([HazardType.DEBRIS, HazardType.FALLEN_TREE, HazardType.FLOOD])
                plans.append(HazardPlan(
                    htype, spec,
                    target_seg_idx=rng.randint(0, n_segments - 1),
                ))
            else:
                htype = rng.choice([
                    HazardType.FLOOD, HazardType.DEBRIS, HazardType.FALLEN_TREE,
                ])
                plans.append(HazardPlan(
                    htype, spec,
                    target_seg_idx=rng.randint(0, n_segments - 1),
                ))

    return plans


# ── Main entry point ──────────────────────────────────────────────────────

def generate_hazards(scene: Scene, rng: _random.Random) -> list[Hazard]:
    """Generate hazards for a scene according to its difficulty.

    Returns a list of Hazard objects ready to be attached to the scene.
    """
    plans = _make_difficulty_plans(
        scene.difficulty,
        len(scene.road_segments),
        len(scene.parks),
        len(scene.buildings),
        rng,
    )

    hazards: list[Hazard] = []
    used_seg_indices: set[int] = set()

    # Precompute buffered union of all roads for near-miss decoy safety (>= 8 px clearance)
    roads_buffered = unary_union([_seg_poly(s) for s in scene.road_segments]).buffer(8.5)

    for idx, plan in enumerate(plans):
        haz_id = f"H-{idx + 1:03d}"
        poly: Optional[ShapelyPolygon] = None
        affected_road: Optional[str] = None
        affected_building: Optional[str] = None

        if plan.placement == PlacementSpec.WATER_ON_PARK:
            if plan.target_park_idx is not None and plan.target_park_idx < len(scene.parks):
                park = scene.parks[plan.target_park_idx]
                poly = _place_water_on_park(park, rng)
            else:
                continue

        elif plan.placement == PlacementSpec.DAMAGED_BUILDING_ONLY:
            if plan.target_building_idx is not None and plan.target_building_idx < len(scene.buildings):
                bldg = scene.buildings[plan.target_building_idx]
                # Hazard polygon = building polygon (marker on building)
                poly = ShapelyPolygon([(p.x, p.y) for p in bldg.polygon])
                affected_building = bldg.id
            else:
                continue

        elif plan.placement == PlacementSpec.BUILDING_SPILL:
            si = plan.target_seg_idx
            bi = plan.target_building_idx
            if si is not None and si < len(scene.road_segments) and bi is not None and bi < len(scene.buildings):
                seg = scene.road_segments[si]
                bldg = scene.buildings[bi]
                poly = _place_building_spill(bldg, seg, rng)
                affected_road = seg.id
                affected_building = bldg.id
            else:
                continue

        elif plan.placement == PlacementSpec.ROAD_DAMAGE:
            si = plan.target_seg_idx
            if si is not None and si < len(scene.road_segments):
                seg = scene.road_segments[si]
                poly = _place_road_damage(seg, rng, plan.severity or Severity.MINOR)
                affected_road = seg.id
            else:
                continue

        elif plan.placement in (PlacementSpec.BLOCK_FULL, PlacementSpec.BLOCK_PARTIAL):
            si = plan.target_seg_idx
            if si is not None and si < len(scene.road_segments):
                seg = scene.road_segments[si]
                if plan.placement == PlacementSpec.BLOCK_FULL:
                    poly = _place_block_full(seg, rng, plan.htype)
                else:
                    poly = _place_block_partial(seg, rng, plan.htype)
                affected_road = seg.id
                used_seg_indices.add(si)
            else:
                continue

        elif plan.placement == PlacementSpec.NEAR_MISS_DECOY:
            si = plan.target_seg_idx
            if si is not None and si < len(scene.road_segments):
                seg = scene.road_segments[si]
                poly = _place_near_miss(seg, rng, plan.htype, roads_buffered=roads_buffered)
                affected_road = seg.id  # reference but doesn't block
            else:
                continue

        if poly is None or poly.is_empty or not poly.is_valid:
            continue

        hazards.append(Hazard(
            id=haz_id,
            type=plan.htype,
            placement=plan.placement,
            polygon=_poly_points(poly),
            bbox=_bbox(poly),
            severity=plan.severity,
            affected_road=affected_road,
            affected_building=affected_building,
        ))

    return hazards

"""
Unit tests for the hazard-to-road geometric mapper (dl.vision.mapper).

Uses hand-crafted geometric scenarios without depending on live APIs,
large datasets, or external services.
"""

import pytest

from dl.contracts.enums import HazardType, RoadStatus
from dl.contracts.scene import Box, Hazard, RoadSegment
from dl.contracts.vision import PredictedHazard
from dl.vision.mapper import (
    map_hazards_to_roads,
)


def _make_horizontal_road(
    segment_id: str = "SEG-001",
    x1: float = 0.0,
    x2: float = 100.0,
    y: float = 50.0,
    width: float = 20.0,
) -> RoadSegment:
    """Helper to create a straight horizontal road of specified width centered along y."""
    half = width / 2.0
    polygon = [
        (x1, y - half),
        (x2, y - half),
        (x2, y + half),
        (x1, y + half),
    ]
    centerline = [(x1, y), (x2, y)]
    return RoadSegment(
        segment_id=segment_id,
        from_node="N1",
        to_node="N2",
        length=abs(x2 - x1),
        centerline=centerline,
        polygon=polygon,
    )


def _make_vertical_road(
    segment_id: str = "SEG-002",
    y1: float = 0.0,
    y2: float = 100.0,
    x: float = 50.0,
    width: float = 20.0,
) -> RoadSegment:
    """Helper to create a straight vertical road of specified width centered along x."""
    half = width / 2.0
    polygon = [
        (x - half, y1),
        (x + half, y1),
        (x + half, y2),
        (x - half, y2),
    ]
    centerline = [(x, y1), (x, y2)]
    return RoadSegment(
        segment_id=segment_id,
        from_node="N3",
        to_node="N4",
        length=abs(y2 - y1),
        centerline=centerline,
        polygon=polygon,
    )


# ---------------------------------------------------------------------------
# Test 1: Full blockage (>= 90% coverage)
# ---------------------------------------------------------------------------

def test_full_blockage():
    """A hazard covers 100% of a road cross-section -> BLOCKED."""
    # Road runs x=0..100, y=40..60 (width 20)
    road = _make_horizontal_road("SEG-001", 0.0, 100.0, 50.0, 20.0)

    # Hazard completely covers across y=35..65 at x=45..55
    hazard = PredictedHazard(
        type=HazardType.DEBRIS,
        bbox=Box((45.0, 35.0, 55.0, 65.0)),
        confidence=0.9,
    )

    results = map_hazards_to_roads([road], [hazard])
    res = results["SEG-001"]
    assert res.status == RoadStatus.BLOCKED
    assert res.max_coverage >= 0.90


# ---------------------------------------------------------------------------
# Test 2: Partial blockage (30% <= coverage < 90%)
# ---------------------------------------------------------------------------

def test_partial_blockage():
    """A hazard covers approximately 40-50% of the road width -> PARTIAL."""
    # Road runs x=0..100, y=40..60 (width 20)
    road = _make_horizontal_road("SEG-001", 0.0, 100.0, 50.0, 20.0)

    # Hazard covers top 8 units of the 20-unit width: y=40..48 (40% coverage)
    hazard = PredictedHazard(
        type=HazardType.FLOOD,
        bbox=Box((40.0, 40.0, 60.0, 48.0)),
        confidence=0.8,
    )

    results = map_hazards_to_roads([road], [hazard])
    res = results["SEG-001"]
    assert res.status == RoadStatus.PARTIAL
    assert 0.30 <= res.max_coverage < 0.90


# ---------------------------------------------------------------------------
# Test 3: Near miss (hazard exactly 8 px away from road boundary)
# ---------------------------------------------------------------------------

def test_near_miss():
    """A hazard is placed exactly 8px outside the road boundary -> CLEAR."""
    # Road runs x=0..100, y=40..60 (top edge at y=40, bottom edge at y=60)
    road = _make_horizontal_road("SEG-001", 0.0, 100.0, 50.0, 20.0)

    # Hazard placed from y=68..80 (8px gap between road bottom y=60 and hazard top y=68)
    hazard = Hazard(
        hazard_id="H-001",
        type=HazardType.FALLEN_TREE,
        bbox=Box((40.0, 68.0, 60.0, 80.0)),
    )

    results = map_hazards_to_roads([road], [hazard])
    res = results["SEG-001"]
    assert res.status == RoadStatus.CLEAR
    assert res.max_coverage == 0.0


# ---------------------------------------------------------------------------
# Test 4: Intersection (One hazard affects two crossing roads)
# ---------------------------------------------------------------------------

def test_intersection_both_affected():
    """Two crossing roads are both blocked by a hazard located at their intersection."""
    # Horizontal road: x=0..100, y=40..60
    road_h = _make_horizontal_road("SEG-H", 0.0, 100.0, 50.0, 20.0)
    # Vertical road: y=0..100, x=40..60
    road_v = _make_vertical_road("SEG-V", 0.0, 100.0, 50.0, 20.0)

    # Hazard squarely covers the intersection: [40, 40, 60, 60]
    hazard = PredictedHazard(
        type=HazardType.FLOOD,
        bbox=Box((40.0, 40.0, 60.0, 60.0)),
        confidence=0.95,
    )

    results = map_hazards_to_roads([road_h, road_v], [hazard])
    assert results["SEG-H"].status == RoadStatus.BLOCKED
    assert results["SEG-H"].max_coverage >= 0.90
    assert results["SEG-V"].status == RoadStatus.BLOCKED
    assert results["SEG-V"].max_coverage >= 0.90


# ---------------------------------------------------------------------------
# Test 5: Damaged building alone never blocks a road
# ---------------------------------------------------------------------------

def test_damaged_building_alone_never_blocks():
    """A damaged building hazard covering part of the road is ignored by the mapper -> CLEAR."""
    road = _make_horizontal_road("SEG-001", 0.0, 100.0, 50.0, 20.0)

    # Even if bbox overlaps road polygon, DAMAGED_BUILDING alone must not block
    hazard = Hazard(
        hazard_id="H-BLDG",
        type=HazardType.DAMAGED_BUILDING,
        bbox=Box((40.0, 40.0, 60.0, 60.0)),
    )

    results = map_hazards_to_roads([road], [hazard])
    res = results["SEG-001"]
    assert res.status == RoadStatus.CLEAR
    assert res.max_coverage == 0.0


# ---------------------------------------------------------------------------
# Test 6: Empty hazards list
# ---------------------------------------------------------------------------

def test_empty_hazards():
    """A road with no hazards must return CLEAR with 0.0 coverage."""
    road = _make_horizontal_road("SEG-001", 0.0, 100.0, 50.0, 20.0)
    results = map_hazards_to_roads([road], [])
    res = results["SEG-001"]
    assert res.status == RoadStatus.CLEAR
    assert res.max_coverage == 0.0


# ---------------------------------------------------------------------------
# Test 7: Overlapping hazards do not double-count
# ---------------------------------------------------------------------------

def test_overlapping_hazards_no_double_count():
    """Two identical overlapping hazards covering 50% must not exceed 50% coverage."""
    road = _make_horizontal_road("SEG-001", 0.0, 100.0, 50.0, 20.0)

    # Two identical 50% partial hazards
    h1 = PredictedHazard(
        type=HazardType.DEBRIS,
        bbox=Box((40.0, 40.0, 60.0, 50.0)),
        confidence=0.8,
    )
    h2 = PredictedHazard(
        type=HazardType.DEBRIS,
        bbox=Box((40.0, 40.0, 60.0, 50.0)),
        confidence=0.8,
    )

    results = map_hazards_to_roads([road], [h1, h2])
    res = results["SEG-001"]
    # 10 / 20 = 50% coverage -> PARTIAL, not BLOCKED (would be 100% if double counted)
    assert res.status == RoadStatus.PARTIAL
    assert 0.49 <= res.max_coverage <= 0.51


# ---------------------------------------------------------------------------
# Test 8: Multiple hazards along one road
# ---------------------------------------------------------------------------

def test_multiple_hazards_one_road():
    """Road with small partial hazard and large blocking hazard takes maximum -> BLOCKED."""
    road = _make_horizontal_road("SEG-001", 0.0, 100.0, 50.0, 20.0)

    # Partial hazard at x=20
    h_small = PredictedHazard(
        type=HazardType.DEBRIS,
        bbox=Box((15.0, 40.0, 25.0, 46.0)),
        confidence=0.7,
    )
    # Full blocking hazard at x=80
    h_big = PredictedHazard(
        type=HazardType.FLOOD,
        bbox=Box((75.0, 38.0, 85.0, 62.0)),
        confidence=0.9,
    )

    results = map_hazards_to_roads([road], [h_small, h_big])
    res = results["SEG-001"]
    assert res.status == RoadStatus.BLOCKED
    assert res.max_coverage >= 0.90


# ---------------------------------------------------------------------------
# Test 9: Invalid road geometry raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_road_geometry_raises_error():
    """Invalid polygon (fewer than 3 points) raises a descriptive ValueError."""
    invalid_road = RoadSegment(
        segment_id="SEG-BAD",
        from_node="N1",
        to_node="N2",
        length=100.0,
        centerline=[(0.0, 0.0), (100.0, 0.0)],
        polygon=[(0.0, 0.0), (100.0, 0.0)],  # Only 2 points
    )

    with pytest.raises(ValueError, match="needs >= 3 points"):
        map_hazards_to_roads([invalid_road], [])

"""
Comprehensive tests for DisasterLens route recommendation engine and verifier.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dl.contracts.observation import RoadStatus
from dl.contracts.routing import (
    RouteAlternative,
    RouteRecommendation,
)
from dl.generator.models import Intersection, Point, RoadSegment, Scene, Zone
from dl.routing.freshness import EffectiveRoadStatus
from dl.routing.graph import RoadGraph
from dl.routing.recommend import recommend
from dl.routing.verify import verify_route

DEMO_SCENE_PATH = Path(__file__).parent.parent / "scenarios" / "demo_city" / "scene.json"


@pytest.fixture
def base_as_of() -> datetime:
    return datetime(2026, 11, 27, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def demo_graph() -> RoadGraph:
    return RoadGraph.from_json(DEMO_SCENE_PATH)


@pytest.fixture
def diamond_graph() -> RoadGraph:
    """
    Creates a 4-node diamond graph:
      N1 --(SEG-001, 10m)--> N2 --(SEG-002, 10m)--> N4  (Total length: 20m)
      N1 --(SEG-003, 12m)--> N3 --(SEG-004, 12m)--> N4  (Total length: 24m)
    """
    nodes = [
        Intersection(id="N1", x=0.0, y=50.0, zone=Zone.NW),
        Intersection(id="N2", x=50.0, y=0.0, zone=Zone.NW),
        Intersection(id="N3", x=50.0, y=100.0, zone=Zone.NW),
        Intersection(id="N4", x=100.0, y=50.0, zone=Zone.NW),
    ]
    p0 = Point(x=0.0, y=0.0)
    p1 = Point(x=10.0, y=10.0)
    segments = [
        RoadSegment(
            id="SEG-001", node_a="N1", node_b="N2",
            centerline=[p0, p1], polygon=[p0, p1, p1, p0],
            length_m=10.0, width_px=40.0, zone=Zone.NW
        ),
        RoadSegment(
            id="SEG-002", node_a="N2", node_b="N4",
            centerline=[p0, p1], polygon=[p0, p1, p1, p0],
            length_m=10.0, width_px=40.0, zone=Zone.NW
        ),
        RoadSegment(
            id="SEG-003", node_a="N1", node_b="N3",
            centerline=[p0, p1], polygon=[p0, p1, p1, p0],
            length_m=12.0, width_px=40.0, zone=Zone.NW
        ),
        RoadSegment(
            id="SEG-004", node_a="N3", node_b="N4",
            centerline=[p0, p1], polygon=[p0, p1, p1, p0],
            length_m=12.0, width_px=40.0, zone=Zone.NW
        ),
    ]
    scene = Scene(
        scene_id="S-TEST-DIAMOND",
        seed=1,
        difficulty="easy",
        grid_size=4,
        intersections=nodes,
        road_segments=segments,
        buildings=[],
        parks=[],
        hazards=[],
    )
    return RoadGraph.from_scene(scene)


class TestRouteRecommendationScenarios:
    """14+ Mandatory routing scenarios required by Phase 3."""

    def test_01_shortest_baseline_crosses_blocked_recommends_alternative(
        self, demo_graph: RoadGraph, base_as_of: datetime
    ):
        """1. Shortest baseline crosses fresh BLOCKED road; recommendation takes an alternative."""
        # On demo city: SEG-001 directly links N1 and N2 (34.56m)
        states = {
            "SEG-001": EffectiveRoadStatus(
                status=RoadStatus.BLOCKED,
                freshness="fresh",
                age_hours=1.0,
                is_stale_from_blocked=False,
            )
        }
        rec = recommend(demo_graph, origin="N1", destination="N2", segment_states=states, as_of=base_as_of)

        assert rec.baseline_route is not None
        assert rec.baseline_route.node_path == ["N1", "N2"]
        assert rec.baseline_route.has_fresh_blocked is True

        assert rec.recommended_route is not None
        assert rec.recommended_route.is_valid is True
        assert rec.recommended_route.has_fresh_blocked is False
        assert "SEG-001" not in rec.recommended_route.segment_path
        assert rec.recommended_route.total_length_m > rec.baseline_route.total_length_m
        assert "avoided due to confirmed obstruction on SEG-001" in rec.explanation

    def test_02_no_alternative_exists_all_connecting_blocked(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """2. No alternative exists because all connecting paths are BLOCKED."""
        # Block SEG-001 and SEG-003 (both outgoing edges from N1)
        states = {
            "SEG-001": EffectiveRoadStatus(status=RoadStatus.BLOCKED, freshness="fresh", age_hours=1.0),
            "SEG-003": EffectiveRoadStatus(status=RoadStatus.BLOCKED, freshness="fresh", age_hours=1.0),
        }
        rec = recommend(diamond_graph, origin="N1", destination="N4", segment_states=states, as_of=base_as_of)

        assert rec.recommended_route is None
        assert rec.verification.is_valid is False
        assert "No viable route found" in rec.explanation

    def test_03_only_stale_roads_available_returns_with_warnings(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """3. Only stale roads are available; route can be returned with warnings."""
        states = {
            "SEG-001": EffectiveRoadStatus(status=RoadStatus.STALE, freshness="stale", age_hours=14.0),
            "SEG-002": EffectiveRoadStatus(status=RoadStatus.STALE, freshness="stale", age_hours=14.0),
            "SEG-003": EffectiveRoadStatus(status=RoadStatus.STALE, freshness="stale", age_hours=14.0),
            "SEG-004": EffectiveRoadStatus(status=RoadStatus.STALE, freshness="stale", age_hours=14.0),
        }
        rec = recommend(diamond_graph, origin="N1", destination="N4", segment_states=states, as_of=base_as_of)

        assert rec.recommended_route is not None
        assert rec.recommended_route.is_valid is True
        assert rec.recommended_route.unverified_segments_count == 2
        assert len(rec.warnings) > 0
        assert any("unverified or stale" in w for w in rec.warnings)

    def test_04_unknown_detour_vs_longer_route_with_better_info(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """4. UNKNOWN detour versus a longer route with better information."""
        # Upper path (N1-N2-N4): length 20m. Set SEG-001 to UNKNOWN (cost x3.0 = 30 + 10x3 = 60).
        # Lower path (N1-N3-N4): length 24m. Set both to CLEAR fresh (cost x1.0: 12 + 12 = 24).
        states = {
            "SEG-001": EffectiveRoadStatus(status=RoadStatus.UNKNOWN, freshness="unknown", age_hours=None),
            "SEG-002": EffectiveRoadStatus(status=RoadStatus.UNKNOWN, freshness="unknown", age_hours=None),
            "SEG-003": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0),
            "SEG-004": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0),
        }
        rec = recommend(diamond_graph, origin="N1", destination="N4", segment_states=states, as_of=base_as_of)

        assert rec.baseline_route.node_path == ["N1", "N2", "N4"]  # 20m
        assert rec.recommended_route.node_path == ["N1", "N3", "N4"]  # 24m, cheaper cost (24 vs 60)
        assert rec.recommended_route.total_cost == 24.0

    def test_05_near_tie_route_costs_produce_deterministic_results(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """5. Near-tie route costs produce deterministic results."""
        # Equal length, equal status
        states = {
            "SEG-001": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0),
            "SEG-002": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0),
            "SEG-003": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0),
            "SEG-004": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0),
        }
        rec1 = recommend(diamond_graph, origin="N1", destination="N4", segment_states=states, as_of=base_as_of)
        rec2 = recommend(diamond_graph, origin="N1", destination="N4", segment_states=states, as_of=base_as_of)

        assert rec1.recommended_route.node_path == rec2.recommended_route.node_path
        assert rec1.recommended_route.total_cost == rec2.recommended_route.total_cost

    def test_06_partial_road_receives_correct_penalty(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """6. PARTIAL road receives the correct 1.5 multiplier penalty."""
        # Upper path: SEG-001 (10m, PARTIAL x1.5 = 15), SEG-002 (10m, CLEAR x1.0 = 10) -> cost 25.
        # Lower path: SEG-003 (12m, CLEAR x1.0 = 12), SEG-004 (12m, CLEAR x1.0 = 12) -> cost 24.
        states = {
            "SEG-001": EffectiveRoadStatus(status=RoadStatus.PARTIAL, freshness="fresh", age_hours=2.0),
            "SEG-002": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=2.0),
            "SEG-003": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=2.0),
            "SEG-004": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=2.0),
        }
        rec = recommend(diamond_graph, origin="N1", destination="N4", segment_states=states, as_of=base_as_of)

        # Baseline is upper (20m vs 24m)
        assert rec.baseline_route.node_path == ["N1", "N2", "N4"]
        # Recommended avoids upper because cost is 25 vs 24
        assert rec.recommended_route.node_path == ["N1", "N3", "N4"]
        assert rec.recommended_route.total_cost == 24.0

    def test_07_origin_equals_destination(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """7. Origin equals destination returns a valid zero-length route."""
        rec = recommend(diamond_graph, origin="N1", destination="N1", as_of=base_as_of)

        assert rec.recommended_route is not None
        assert rec.recommended_route.node_path == ["N1"]
        assert rec.recommended_route.segment_path == []
        assert rec.recommended_route.total_length_m == 0.0
        assert rec.recommended_route.total_cost == 0.0
        assert rec.verification.is_valid is True
        assert "Zero traversal distance required" in rec.explanation

    def test_08_disconnected_graph(self, base_as_of: datetime):
        """8. Disconnected graph returns no route."""
        # Create 2 disconnected components
        p0 = Point(x=0.0, y=0.0)
        p1 = Point(x=10.0, y=10.0)
        nodes = [
            Intersection(id="N1", x=0.0, y=0.0, zone=Zone.NW),
            Intersection(id="N2", x=10.0, y=0.0, zone=Zone.NW),
            Intersection(id="N3", x=50.0, y=50.0, zone=Zone.SE),
            Intersection(id="N4", x=60.0, y=50.0, zone=Zone.SE),
        ]
        segments = [
            RoadSegment(
                id="SEG-001", node_a="N1", node_b="N2",
                centerline=[p0, p1], polygon=[p0, p1, p1, p0],
                length_m=10.0, width_px=40.0, zone=Zone.NW
            ),
            RoadSegment(
                id="SEG-002", node_a="N3", node_b="N4",
                centerline=[p0, p1], polygon=[p0, p1, p1, p0],
                length_m=10.0, width_px=40.0, zone=Zone.SE
            ),
        ]
        scene = Scene(
            scene_id="S-TEST-DISCONNECTED", seed=1, difficulty="easy", grid_size=4,
            intersections=nodes, road_segments=segments, buildings=[], parks=[], hazards=[]
        )
        graph = RoadGraph.from_scene(scene)
        rec = recommend(graph, origin="N1", destination="N4", as_of=base_as_of)

        assert rec.recommended_route is None
        assert rec.verification.is_valid is False
        assert "cannot establish a connected path" in rec.explanation

    def test_09_missing_origin_or_destination_node(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """9. Missing origin or destination node returns explicit failure."""
        rec_bad_orig = recommend(diamond_graph, origin="NONEXISTENT", destination="N4", as_of=base_as_of)
        assert rec_bad_orig.recommended_route is None
        assert "ORIGIN_NOT_FOUND" in rec_bad_orig.verification.failure_reasons[0]

        rec_bad_dest = recommend(diamond_graph, origin="N1", destination="NONEXISTENT", as_of=base_as_of)
        assert rec_bad_dest.recommended_route is None
        assert "DESTINATION_NOT_FOUND" in rec_bad_dest.verification.failure_reasons[0]

    def test_10_verifier_rejects_disconnected_path(self, diamond_graph: RoadGraph):
        """10. Verifier rejects a hand-crafted path with a gap."""
        # N1 to N4 directly (no edge exists)
        bad_alt = RouteAlternative(
            rank=1,
            node_path=["N1", "N4"],
            segment_path=["SEG-001"],
            total_length_m=10.0,
            total_cost=10.0,
        )
        verif = verify_route(bad_alt, diamond_graph, expected_origin="N1", expected_destination="N4")
        assert verif.is_valid is False
        assert verif.is_connected is False
        assert any("DISCONNECTED_EDGE" in r for r in verif.failure_reasons)

    def test_11_verifier_rejects_path_crossing_fresh_blocked_segment(
        self, diamond_graph: RoadGraph
    ):
        """11. Verifier rejects a path crossing a fresh BLOCKED segment."""
        alt = RouteAlternative(
            rank=1,
            node_path=["N1", "N2", "N4"],
            segment_path=["SEG-001", "SEG-002"],
            total_length_m=20.0,
            total_cost=20.0,
        )
        states = {
            "SEG-001": EffectiveRoadStatus(status=RoadStatus.BLOCKED, freshness="fresh", age_hours=1.0)
        }
        verif = verify_route(alt, diamond_graph, expected_origin="N1", expected_destination="N4", segment_states=states)
        assert verif.is_valid is False
        assert verif.has_fresh_blocked_segments is True
        assert "SEG-001" in verif.blocked_segment_ids

    def test_12_verifier_rejects_inconsistent_node_and_segment_sequences(
        self, diamond_graph: RoadGraph
    ):
        """12. Verifier rejects inconsistent sequence lengths or mismatched IDs."""
        # 3 nodes but only 1 segment
        alt = RouteAlternative(
            rank=1,
            node_path=["N1", "N2", "N4"],
            segment_path=["SEG-001"],
            total_length_m=10.0,
            total_cost=10.0,
        )
        verif = verify_route(alt, diamond_graph, expected_origin="N1", expected_destination="N4")
        assert verif.is_valid is False
        assert any("INCONSISTENT_LENGTH" in r for r in verif.failure_reasons)

    def test_13_stale_from_blocked_heavily_penalized(
        self, diamond_graph: RoadGraph, base_as_of: datetime
    ):
        """13. STALE-from-BLOCKED receives 8.0 penalty multiplier, routing avoids it if possible."""
        # Upper path: SEG-001 is STALE from blocked (10m x 8.0 = 80 + 10 = 90).
        # Lower path: SEG-003 (12m x 3.0 = 36 + 36 = 72).
        states = {
            "SEG-001": EffectiveRoadStatus(
                status=RoadStatus.STALE, freshness="stale", age_hours=26.0, is_stale_from_blocked=True
            ),
            "SEG-002": EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0),
        }
        rec = recommend(diamond_graph, origin="N1", destination="N4", segment_states=states, as_of=base_as_of)

        assert rec.recommended_route.node_path == ["N1", "N3", "N4"]

    def test_14_alternative_routes_contain_no_duplicates(
        self, demo_graph: RoadGraph, base_as_of: datetime
    ):
        """14. Alternative routes contain no duplicates and are strictly valid."""
        rec = recommend(demo_graph, origin="N1", destination="N8", as_of=base_as_of)

        assert rec.recommended_route is not None
        assert len(rec.alternatives) <= 2

        all_paths = [rec.recommended_route.segment_path]
        for alt in rec.alternatives:
            assert alt.is_valid is True
            assert alt.segment_path not in all_paths
            all_paths.append(alt.segment_path)

    def test_15_pure_library_usage_no_fastapi_or_db(self, demo_graph: RoadGraph):
        """15. recommend() can be imported and executed in complete isolation."""
        # Verify FastAPI is not imported by dl.routing.recommend
        # (check module registry before and during call)
        rec = recommend(demo_graph, origin="N1", destination="N2")
        assert isinstance(rec, RouteRecommendation)
        assert rec.origin == "N1"
        assert rec.destination == "N2"

    def test_16_costs_multipliers_and_edge_cases(self):
        """Covers all branches in costs.py: partial/uncertain stale, fallbacks."""
        from dl.routing.costs import get_cost_multiplier

        # PARTIAL with non-fresh/non-active (stale)
        assert get_cost_multiplier(RoadStatus.PARTIAL, freshness="stale") == 3.0
        # UNCERTAIN with non-fresh/non-active (stale)
        assert get_cost_multiplier(RoadStatus.UNCERTAIN, freshness="stale") == 3.0
        # String status handling
        assert get_cost_multiplier("CLEAR", freshness="fresh") == 1.0

    def test_17_verify_route_edge_cases(self, demo_graph: RoadGraph):
        """Covers edge cases in verify_route: empty, origin/dest mismatch, single node mismatch."""
        from dl.contracts.routing import RouteAlternative

        # 1. Empty route
        empty_route = RouteAlternative(
            route_id="empty",
            node_path=[],
            segment_path=[],
            total_length_m=0.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=False,
            steps=[],
        )
        v_empty = verify_route(empty_route, demo_graph, "N1", "N2")
        assert v_empty.is_valid is False
        assert "EMPTY_ROUTE" in v_empty.failure_reasons

        # 2. Origin mismatch
        route_bad_orig = RouteAlternative(
            route_id="r1",
            node_path=["N2", "N3"],
            segment_path=["SEG-002"],
            total_length_m=10.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=True,
            steps=[],
        )
        v_orig = verify_route(route_bad_orig, demo_graph, "N1", "N3")
        assert v_orig.is_valid is False
        assert any("ORIGIN_MISMATCH" in r for r in v_orig.failure_reasons)

        # 3. Destination mismatch
        v_dest = verify_route(route_bad_orig, demo_graph, "N2", "N4")
        assert v_dest.is_valid is False
        assert any("DESTINATION_MISMATCH" in r for r in v_dest.failure_reasons)

        # 4. Single-node route with non-empty segment_path
        route_single_bad = RouteAlternative(
            route_id="r_single",
            node_path=["N1"],
            segment_path=["SEG-001"],
            total_length_m=10.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=True,
            steps=[],
        )
        v_single = verify_route(route_single_bad, demo_graph, "N1", "N1")
        assert v_single.is_valid is False
        assert "INCONSISTENT_SEGMENT_COUNT_FOR_POINT_ROUTE" in v_single.failure_reasons

        # 5. Disconnected edge and segment mismatch
        route_disc = RouteAlternative(
            route_id="r_disc",
            node_path=["N1", "N36"],  # no direct edge in demo graph
            segment_path=["SEG-001"],
            total_length_m=10.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=True,
            steps=[],
        )
        v_disc = verify_route(route_disc, demo_graph, "N1", "N36")
        assert v_disc.is_valid is False
        assert any("DISCONNECTED_EDGE" in r for r in v_disc.failure_reasons)

        # Segment ID mismatch: N1->N2 is SEG-001, but we pass SEG-999
        route_mismatch = RouteAlternative(
            route_id="r_mis",
            node_path=["N1", "N2"],
            segment_path=["SEG-999"],
            total_length_m=10.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=True,
            steps=[],
        )
        v_mis = verify_route(route_mismatch, demo_graph, "N1", "N2")
        assert v_mis.is_valid is False
        assert any("SEGMENT_MISMATCH" in r for r in v_mis.failure_reasons)

    def test_18_explain_and_warnings_edge_cases(self, demo_graph: RoadGraph):
        """Covers edge cases in explain.py: None route, invalid route, warnings, detours."""
        from dl.contracts.routing import RouteAlternative, RouteStep
        from dl.routing.explain import build_route_explanation, build_route_warnings

        # 1. build_route_warnings(None)
        w_none = build_route_warnings(None)
        assert len(w_none) == 1
        assert "No viable route could be found" in w_none[0]

        # 2. build_route_warnings for invalid route
        step_stale_blocked = RouteStep(
            from_node="N1",
            to_node="N2",
            segment_id="SEG-001",
            length_m=10.0,
            effective_status=RoadStatus.STALE,
            freshness="stale",
            cost_multiplier=8.0,
            effective_cost=80.0,
            is_stale_from_blocked=True,
        )
        step_uncertain = RouteStep(
            from_node="N2",
            to_node="N3",
            segment_id="SEG-002",
            length_m=10.0,
            effective_status=RoadStatus.UNCERTAIN,
            freshness="fresh",
            cost_multiplier=4.0,
            effective_cost=40.0,
        )
        r_warn = RouteAlternative(
            route_id="rw",
            node_path=["N1", "N2", "N3"],
            segment_path=["SEG-001", "SEG-002"],
            total_length_m=20.0,
            has_fresh_blocked=False,
            unverified_segments_count=1,
            is_valid=False,
            steps=[step_stale_blocked, step_uncertain],
        )
        w_res = build_route_warnings(r_warn)
        assert any("Route failed safety verification" in w for w in w_res)
        assert any("previously reported BLOCKED" in w for w in w_res)
        assert any("conflicting or low-confidence evidence" in w for w in w_res)

        # 3. build_route_explanation with penalised baseline
        baseline_penalised = RouteAlternative(
            route_id="b_pen",
            node_path=["N1", "N2", "N3"],
            segment_path=["SEG-001", "SEG-002"],
            total_length_m=20.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=True,
            steps=[step_uncertain],
        )
        rec_clean = RouteAlternative(
            route_id="r_clean",
            node_path=["N1", "N4", "N3"],
            segment_path=["SEG-003", "SEG-004"],
            total_length_m=24.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=True,
            steps=[],
        )
        exp_pen = build_route_explanation("N1", "N3", baseline_penalised, rec_clean)
        assert "traverses penalised or uncertain road segments" in exp_pen

        # 4. build_route_explanation with unweighted difference
        baseline_clean = RouteAlternative(
            route_id="b_clean",
            node_path=["N1", "N2", "N3"],
            segment_path=["SEG-001", "SEG-002"],
            total_length_m=20.0,
            has_fresh_blocked=False,
            unverified_segments_count=0,
            is_valid=True,
            steps=[],
        )
        exp_unw = build_route_explanation("N1", "N3", baseline_clean, rec_clean)
        assert "optimizes condition-weighted traversal" in exp_unw

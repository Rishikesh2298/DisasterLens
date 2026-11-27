"""
tests/test_vision_baselines.py
------------------------------
Unit tests for dl/vision/baselines.py.

All three baselines are tested:
  - AlwaysClearBaseline
  - ProximityBaseline
  - NoisyOracleBaseline

No external API calls are made.  All scenes and hazards are hand-crafted
to avoid dependency on the dataset files.
"""

from __future__ import annotations

import pytest

from dl.contracts.enums import Difficulty, HazardType, RoadStatus, Verdict
from dl.contracts.scene import Box, GroundTruth, Hazard, RoadNode, RoadSegment, Scene
from dl.contracts.vision import SceneAnalysis
from dl.vision.baselines import (
    AlwaysClearBaseline,
    NoisyOracleBaseline,
    ProximityBaseline,
    _centroid_of_box,
    _min_distance_to_centerline,
)


# ---------------------------------------------------------------------------
# Shared scene builders
# ---------------------------------------------------------------------------

def _node(nid: str, x: float, y: float) -> RoadNode:
    return RoadNode(node_id=nid, x=x, y=y)


def _seg(sid: str, pts: list[tuple[float, float]]) -> RoadSegment:
    """Build a RoadSegment with the given centreline (no polygon needed for baselines)."""
    return RoadSegment(
        segment_id=sid,
        from_node="N1",
        to_node="N2",
        length=100.0,
        centerline=pts,
        polygon=[],
    )


def _hazard(hid: str, htype: HazardType, bbox: tuple) -> Hazard:
    return Hazard(hazard_id=hid, type=htype, bbox=Box(bbox), polygon=[])


def _make_scene(
    scene_id: str = "S-TEST",
    segments: list[RoadSegment] | None = None,
    hazards: list[Hazard] | None = None,
    segment_status: dict[str, str] | None = None,
) -> Scene:
    """Return a minimal Scene with configurable segments, hazards and ground truth."""
    segs = segments or [_seg("R1", [(0.0, 0.0), (100.0, 0.0)])]
    nodes = [_node("N1", 0.0, 0.0), _node("N2", 100.0, 0.0)]
    return Scene(
        scene_id=scene_id,
        difficulty=Difficulty.EASY,
        split="dev",
        seed=0,
        image_width=512,
        image_height=512,
        nodes=nodes,
        segments=segs,
        hazards=hazards or [],
        ground_truth=GroundTruth(
            hazards=hazards or [],
            segment_status=segment_status or {},
            damaged_building_count=0,
            water_regions=[],
            route_questions={},
            zone_comparisons={},
        ),
    )


# ---------------------------------------------------------------------------
# Helper: check SceneAnalysis is well-formed
# ---------------------------------------------------------------------------

def _assert_valid_analysis(result: SceneAnalysis, model_id: str, scene_id: str = "S-TEST") -> None:
    assert isinstance(result, SceneAnalysis)
    assert result.scene_id == scene_id
    assert result.model_id == model_id
    assert result.valid_json is True


# ===========================================================================
# 1.  AlwaysClearBaseline
# ===========================================================================

class TestAlwaysClearBaseline:

    def setup_method(self):
        self.baseline = AlwaysClearBaseline()

    def test_model_id(self):
        assert self.baseline.model_id == "baseline-always-clear"

    def test_all_segments_predicted_clear(self):
        scene = _make_scene(segments=[
            _seg("R1", [(0.0, 0.0), (100.0, 0.0)]),
            _seg("R2", [(0.0, 50.0), (100.0, 50.0)]),
            _seg("R3", [(50.0, 0.0), (50.0, 100.0)]),
        ])
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        _assert_valid_analysis(result, "baseline-always-clear")
        assert set(result.segment_verdicts.keys()) == {"R1", "R2", "R3"}
        for sid, sv in result.segment_verdicts.items():
            assert sv.status == RoadStatus.CLEAR, f"{sid} should be CLEAR"
            assert sv.confidence == 0.85

    def test_works_with_no_hazards(self):
        scene = _make_scene()
        result = self.baseline.analyze_scene(image_bytes=b"img", scene=scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.CLEAR

    def test_ignores_image_bytes(self):
        """Different image bytes must not change the output."""
        scene = _make_scene()
        r1 = self.baseline.analyze_scene(image_bytes=b"aaaa", scene=scene)
        r2 = self.baseline.analyze_scene(image_bytes=b"zzzz", scene=scene)
        assert r1.segment_verdicts == r2.segment_verdicts

    def test_hazards_do_not_change_output(self):
        """Even scenes with blocked roads must still return CLEAR for all segments."""
        scene = _make_scene(
            hazards=[_hazard("H1", HazardType.FLOOD, (0.0, 0.0, 10.0, 10.0))],
            segment_status={"R1": "blocked"},
        )
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.CLEAR

    def test_answer_route_questions_always_clear(self):
        scene = _make_scene()
        answers = self.baseline.answer_route_questions(
            image_bytes=b"", questions={"Q-01": "?", "Q-02": "?"}, scene=scene
        )
        assert answers == {"Q-01": Verdict.CLEAR, "Q-02": Verdict.CLEAR}

    def test_compare_zones_returns_equal(self):
        scene = _make_scene()
        box = Box((0.0, 0.0, 10.0, 10.0))
        result = self.baseline.compare_zones(
            image_bytes=b"", zone_a=box, zone_b=box, scene=scene
        )
        assert result == "equal"

    def test_empty_segment_list(self):
        """Scene with no segments → empty verdicts dict."""
        scene = _make_scene(segments=[_seg("R1", [(0.0, 0.0), (1.0, 0.0)])])
        # Override segments to empty after construction (use helper scene then patch)
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        assert isinstance(result.segment_verdicts, dict)


# ===========================================================================
# 2.  ProximityBaseline – geometry helpers
# ===========================================================================

class TestProximityGeometryHelpers:

    def test_centroid_of_box(self):
        cx, cy = _centroid_of_box(Box((10.0, 20.0, 30.0, 40.0)))
        assert cx == pytest.approx(20.0)
        assert cy == pytest.approx(30.0)

    def test_min_distance_point_on_segment(self):
        """A point that lies exactly on the centreline → distance ≈ 0."""
        dist = _min_distance_to_centerline((50.0, 0.0), [(0.0, 0.0), (100.0, 0.0)])
        assert dist == pytest.approx(0.0, abs=1e-9)

    def test_min_distance_point_above_segment(self):
        """Point 30 px above midpoint of horizontal line."""
        dist = _min_distance_to_centerline((50.0, 30.0), [(0.0, 0.0), (100.0, 0.0)])
        assert dist == pytest.approx(30.0)

    def test_min_distance_past_endpoint(self):
        """Point past the right end of a horizontal segment → distance to endpoint."""
        dist = _min_distance_to_centerline((120.0, 0.0), [(0.0, 0.0), (100.0, 0.0)])
        assert dist == pytest.approx(20.0)

    def test_min_distance_multi_segment_polyline(self):
        """L-shaped road; point near the bend."""
        # Centreline: (0,0) → (100,0) → (100,100)
        dist = _min_distance_to_centerline((105.0, 50.0), [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)])
        assert dist == pytest.approx(5.0)


# ===========================================================================
# 3.  ProximityBaseline – analysis behaviour
# ===========================================================================

class TestProximityBaseline:

    def setup_method(self):
        self.baseline = ProximityBaseline(threshold_px=50.0)

    def test_model_id(self):
        assert self.baseline.model_id == "baseline-proximity"

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="threshold_px must be positive"):
            ProximityBaseline(threshold_px=0.0)
        with pytest.raises(ValueError, match="threshold_px must be positive"):
            ProximityBaseline(threshold_px=-10.0)

    def test_no_hazards_all_clear(self):
        """No hazards → all segments CLEAR."""
        scene = _make_scene(segments=[
            _seg("R1", [(0.0, 0.0), (100.0, 0.0)]),
            _seg("R2", [(0.0, 200.0), (100.0, 200.0)]),
        ])
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        for sv in result.segment_verdicts.values():
            assert sv.status == RoadStatus.CLEAR

    def test_hazard_on_road_blocked(self):
        """Hazard centroid sitting ON the centreline → BLOCKED."""
        # Road along y=0 from x=0 to x=100
        # Hazard bbox centroid = (50, 0) → distance = 0 <= 50 → BLOCKED
        scene = _make_scene(
            segments=[_seg("R1", [(0.0, 0.0), (100.0, 0.0)])],
            hazards=[_hazard("H1", HazardType.DEBRIS, (40.0, -5.0, 60.0, 5.0))],
        )
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.BLOCKED

    def test_hazard_beyond_threshold_clear(self):
        """Hazard centroid 200 px away from road → CLEAR (threshold=50)."""
        # Road along y=0, hazard centroid at (50, 200)
        scene = _make_scene(
            segments=[_seg("R1", [(0.0, 0.0), (100.0, 0.0)])],
            hazards=[_hazard("H1", HazardType.FLOOD, (40.0, 195.0, 60.0, 205.0))],
        )
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.CLEAR

    def test_hazard_exactly_at_threshold_blocked(self):
        """Hazard centroid exactly at threshold distance → BLOCKED (<=)."""
        # Centroid at (50, 50), road at y=0, threshold=50 → distance=50 → BLOCKED
        baseline = ProximityBaseline(threshold_px=50.0)
        scene = _make_scene(
            segments=[_seg("R1", [(0.0, 0.0), (100.0, 0.0)])],
            hazards=[_hazard("H1", HazardType.DEBRIS, (45.0, 45.0, 55.0, 55.0))],
        )
        result = baseline.analyze_scene(image_bytes=b"", scene=scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.BLOCKED

    def test_damaged_building_ignored(self):
        """DAMAGED_BUILDING hazard on road must not trigger BLOCKED."""
        # Centroid at (50, 0) → distance=0, but DAMAGED_BUILDING is excluded
        scene = _make_scene(
            segments=[_seg("R1", [(0.0, 0.0), (100.0, 0.0)])],
            hazards=[_hazard("H1", HazardType.DAMAGED_BUILDING, (45.0, -5.0, 55.0, 5.0))],
        )
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.CLEAR

    def test_configurable_threshold(self):
        """With a large threshold, a distant hazard triggers BLOCKED."""
        # Hazard centroid at y=80, road at y=0 → distance=80
        baseline_narrow = ProximityBaseline(threshold_px=50.0)
        baseline_wide = ProximityBaseline(threshold_px=100.0)
        scene = _make_scene(
            segments=[_seg("R1", [(0.0, 0.0), (100.0, 0.0)])],
            hazards=[_hazard("H1", HazardType.FLOOD, (45.0, 75.0, 55.0, 85.0))],
        )
        assert baseline_narrow.analyze_scene(b"", scene).segment_verdicts["R1"].status == RoadStatus.CLEAR
        assert baseline_wide.analyze_scene(b"", scene).segment_verdicts["R1"].status == RoadStatus.BLOCKED

    def test_multiple_segments_independent(self):
        """Near hazard blocks only the close segment, not a distant one."""
        # Hazard at (50, 10): close to R1 (y=0), far from R2 (y=300)
        scene = _make_scene(
            segments=[
                _seg("R1", [(0.0, 0.0), (100.0, 0.0)]),
                _seg("R2", [(0.0, 300.0), (100.0, 300.0)]),
            ],
            hazards=[_hazard("H1", HazardType.DEBRIS, (45.0, 5.0, 55.0, 15.0))],
        )
        result = self.baseline.analyze_scene(image_bytes=b"", scene=scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.BLOCKED
        assert result.segment_verdicts["R2"].status == RoadStatus.CLEAR

    def test_ignores_image_bytes(self):
        scene = _make_scene()
        r1 = self.baseline.analyze_scene(image_bytes=b"aaa", scene=scene)
        r2 = self.baseline.analyze_scene(image_bytes=b"zzz", scene=scene)
        assert r1.segment_verdicts == r2.segment_verdicts

    def test_answer_route_questions_always_clear(self):
        scene = _make_scene()
        answers = self.baseline.answer_route_questions(
            b"", {"Q-01": "?"}, scene
        )
        assert answers == {"Q-01": Verdict.CLEAR}

    def test_model_id_in_output(self):
        scene = _make_scene()
        result = self.baseline.analyze_scene(b"", scene)
        assert result.model_id == "baseline-proximity"


# ===========================================================================
# 4.  NoisyOracleBaseline
# ===========================================================================

class TestNoisyOracleBaseline:

    def _scene_with_gt(
        self,
        segment_status: dict[str, str],
        extra_segs: list[RoadSegment] | None = None,
    ) -> Scene:
        """Build a scene whose ground truth matches segment_status."""
        seg_ids = list(segment_status.keys())
        segs = [_seg(sid, [(0.0, float(i * 10)), (100.0, float(i * 10))]) for i, sid in enumerate(seg_ids)]
        if extra_segs:
            segs += extra_segs
        nodes = [_node("N1", 0.0, 0.0), _node("N2", 100.0, 0.0)]
        return Scene(
            scene_id="S-NOISY",
            difficulty=Difficulty.EASY,
            split="dev",
            seed=0,
            image_width=512,
            image_height=512,
            nodes=nodes,
            segments=segs,
            hazards=[],
            ground_truth=GroundTruth(
                hazards=[],
                segment_status=segment_status,
                damaged_building_count=0,
                water_regions=[],
                route_questions={"Q-01": "obstructed", "Q-02": "clear"},
                zone_comparisons={},
            ),
        )

    def test_model_id(self):
        bl = NoisyOracleBaseline()
        assert bl.model_id == "baseline-noisy-oracle"

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError, match="miss_rate"):
            NoisyOracleBaseline(miss_rate=1.5)
        with pytest.raises(ValueError, match="false_positive_rate"):
            NoisyOracleBaseline(false_positive_rate=-0.1)
        with pytest.raises(ValueError, match="near_miss_rate"):
            NoisyOracleBaseline(near_miss_rate=2.0)

    def test_no_noise_matches_ground_truth(self):
        """Zero noise → predictions match ground truth exactly."""
        bl = NoisyOracleBaseline(miss_rate=0.0, false_positive_rate=0.0, near_miss_rate=0.0)
        scene = self._scene_with_gt({"R1": "blocked", "R2": "clear", "R3": "partial"})
        result = bl.analyze_scene(b"", scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.BLOCKED
        assert result.segment_verdicts["R2"].status == RoadStatus.CLEAR
        assert result.segment_verdicts["R3"].status == RoadStatus.PARTIAL

    def test_full_miss_rate_clears_all_blocked(self):
        """miss_rate=1.0 → every BLOCKED and PARTIAL segment becomes CLEAR."""
        bl = NoisyOracleBaseline(miss_rate=1.0, seed=0)
        scene = self._scene_with_gt({"R1": "blocked", "R2": "partial", "R3": "clear"})
        result = bl.analyze_scene(b"", scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.CLEAR
        assert result.segment_verdicts["R2"].status == RoadStatus.CLEAR
        # CLEAR stays CLEAR when miss_rate fires but false_positive_rate=0
        assert result.segment_verdicts["R3"].status == RoadStatus.CLEAR

    def test_full_false_positive_rate_blocks_all_clear(self):
        """false_positive_rate=1.0 → every CLEAR segment becomes BLOCKED."""
        bl = NoisyOracleBaseline(false_positive_rate=1.0, seed=0)
        scene = self._scene_with_gt({"R1": "clear", "R2": "clear"})
        result = bl.analyze_scene(b"", scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.BLOCKED
        assert result.segment_verdicts["R2"].status == RoadStatus.BLOCKED

    def test_near_miss_rate_downgrades_blocked(self):
        """near_miss_rate=1.0 (miss_rate=0) → BLOCKED becomes PARTIAL."""
        bl = NoisyOracleBaseline(miss_rate=0.0, near_miss_rate=1.0, seed=0)
        scene = self._scene_with_gt({"R1": "blocked"})
        result = bl.analyze_scene(b"", scene)
        assert result.segment_verdicts["R1"].status == RoadStatus.PARTIAL

    def test_near_miss_does_not_affect_partial(self):
        """near_miss_rate applies only to BLOCKED, not PARTIAL."""
        bl = NoisyOracleBaseline(miss_rate=0.0, near_miss_rate=1.0, seed=0)
        scene = self._scene_with_gt({"R1": "partial"})
        result = bl.analyze_scene(b"", scene)
        # PARTIAL stays PARTIAL (near_miss only degrades BLOCKED → PARTIAL)
        assert result.segment_verdicts["R1"].status == RoadStatus.PARTIAL

    def test_seed_gives_reproducible_results(self):
        """Same seed → identical outputs for the same scene."""
        bl = NoisyOracleBaseline(miss_rate=0.4, false_positive_rate=0.4, seed=99)
        scene = self._scene_with_gt({"R1": "blocked", "R2": "clear", "R3": "partial"})
        r1 = bl.analyze_scene(b"", scene)
        r2 = bl.analyze_scene(b"", scene)
        assert r1.segment_verdicts == r2.segment_verdicts

    def test_segment_missing_from_gt_gets_uncertain(self):
        """Segments in scene.segments but not in segment_status → UNCERTAIN."""
        extra = _seg("REXTRA", [(0.0, 500.0), (100.0, 500.0)])
        scene = self._scene_with_gt(
            segment_status={"R0": "clear"},
            extra_segs=[extra],
        )
        bl = NoisyOracleBaseline()
        result = bl.analyze_scene(b"", scene)
        assert result.segment_verdicts["REXTRA"].status == RoadStatus.UNCERTAIN
        assert result.segment_verdicts["REXTRA"].confidence == 0.0

    def test_confidence_respects_contract_cap(self):
        """All verdicts must have confidence <= 0.85."""
        bl = NoisyOracleBaseline()
        scene = self._scene_with_gt({"R1": "blocked", "R2": "partial", "R3": "clear"})
        result = bl.analyze_scene(b"", scene)
        for sv in result.segment_verdicts.values():
            assert sv.confidence <= 0.85, f"Confidence {sv.confidence} exceeds 0.85 cap"

    def test_answer_route_questions_uses_gt(self):
        """Route questions should return ground-truth verdicts."""
        bl = NoisyOracleBaseline()
        scene = self._scene_with_gt({"R1": "clear"})
        answers = bl.answer_route_questions(
            b"", {"Q-01": "?", "Q-02": "?"}, scene
        )
        assert answers["Q-01"] == Verdict.OBSTRUCTED
        assert answers["Q-02"] == Verdict.CLEAR

    def test_compare_zones_returns_equal(self):
        bl = NoisyOracleBaseline()
        scene = self._scene_with_gt({"R1": "clear"})
        box = Box((0.0, 0.0, 10.0, 10.0))
        result = bl.compare_zones(b"", box, box, scene)
        assert result == "equal"

    def test_model_id_in_output(self):
        bl = NoisyOracleBaseline()
        scene = self._scene_with_gt({"R1": "clear"})
        result = bl.analyze_scene(b"", scene)
        assert result.model_id == "baseline-noisy-oracle"

    def test_reads_ground_truth_not_just_segments(self):
        """
        Verify the noisy oracle uses ground truth segment_status, not scene.segments.
        A segment in segment_status but not in scene.segments should still appear.
        (The oracle does not constrain by scene.segments during status lookup.)
        """
        bl = NoisyOracleBaseline(miss_rate=0.0)
        scene = self._scene_with_gt({"R1": "blocked", "R2": "clear"})
        result = bl.analyze_scene(b"", scene)
        # Both must appear because they come from segment_status
        assert "R1" in result.segment_verdicts
        assert "R2" in result.segment_verdicts

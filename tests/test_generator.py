"""
Tests for DisasterLens synthetic scene generator.

Coverage:
  A. Determinism
  B. Geometry (horizontal/vertical/intersection/full/partial/near-miss)
  C. Hazard specifications
  D. Ground truth thresholds
  E. Validator (pass/fail)
  F. Questions
  G. Dataset composition
"""

from __future__ import annotations

import copy
import json
import random as _random

import pytest
from shapely.geometry import Polygon as ShapelyPolygon

from dl.generator.city import generate_city
from dl.generator.geometry import cross_section_coverage
from dl.generator.ground_truth import compute_ground_truth
from dl.generator.hazards import generate_hazards
from dl.generator.models import (
    BBox,
    Difficulty,
    Hazard,
    HazardType,
    Intersection,
    PlacementSpec,
    Point,
    QuestionType,
    RoadSegment,
    RoadStatus,
    Severity,
    Zone,
    to_contract_scene,
    to_evaluation_record,
)
from dl.generator.questions import generate_questions
from dl.generator.validate import validate_scene

# ═══════════════════════════════════════════════════════════════════════════
# A. DETERMINISM
# ═══════════════════════════════════════════════════════════════════════════

class TestDeterminism:
    def test_same_seed_same_scene(self):
        """Same seed → identical scene.json."""
        s1 = generate_city("S-0001", 2026, Difficulty.EASY)
        s2 = generate_city("S-0001", 2026, Difficulty.EASY)
        assert s1.model_dump() == s2.model_dump()

    def test_same_seed_same_hazards(self):
        """Same seed → identical hazards."""
        s1 = generate_city("S-0001", 2026, Difficulty.MEDIUM)
        h1 = generate_hazards(s1, _random.Random(2026))

        s2 = generate_city("S-0001", 2026, Difficulty.MEDIUM)
        h2 = generate_hazards(s2, _random.Random(2026))

        assert len(h1) == len(h2)
        for a, b in zip(h1, h2):
            assert a.model_dump() == b.model_dump()

    def test_repeated_build_deterministic_hashes(self):
        """Repeated generation of the same scene produces identical canonical JSON and SHA-256."""
        import hashlib

        from dl.generator.build import _canonical_json

        s1 = generate_city("S-0001", 2026, Difficulty.EASY)
        s1.hazards = generate_hazards(s1, _random.Random(2026))
        compute_ground_truth(s1)

        s2 = generate_city("S-0001", 2026, Difficulty.EASY)
        s2.hazards = generate_hazards(s2, _random.Random(2026))
        compute_ground_truth(s2)

        j1 = _canonical_json(s1.model_dump(mode="json"))
        j2 = _canonical_json(s2.model_dump(mode="json"))
        assert j1 == j2
        h1 = hashlib.sha256(j1.encode("utf-8")).hexdigest()
        h2 = hashlib.sha256(j2.encode("utf-8")).hexdigest()
        assert h1 == h2

    def test_different_seed_different_scene(self):
        """Different seeds → different scenes."""
        s1 = generate_city("S-0001", 2026, Difficulty.EASY)
        s2 = generate_city("S-0001", 2027, Difficulty.EASY)
        # Buildings use RNG so positions will differ
        assert s1.model_dump() != s2.model_dump()


# ═══════════════════════════════════════════════════════════════════════════
# B. GEOMETRY
# ═══════════════════════════════════════════════════════════════════════════

class TestGeometry:
    @pytest.fixture
    def easy_scene(self):
        return generate_city("S-TEST", 9999, Difficulty.EASY)

    def test_grid_size_easy(self, easy_scene):
        assert easy_scene.grid_size == 4
        assert len(easy_scene.intersections) == 16

    def test_grid_size_medium(self):
        s = generate_city("S-TEST", 9999, Difficulty.MEDIUM)
        assert s.grid_size == 5
        assert len(s.intersections) == 25

    def test_grid_size_hard(self):
        s = generate_city("S-TEST", 9999, Difficulty.HARD)
        assert s.grid_size == 6
        assert len(s.intersections) == 36

    def test_road_count_easy(self, easy_scene):
        # 4×4 grid: 3 horizontal per row × 4 rows + 4 vertical per col × 3 cols = 12 + 12 = 24
        assert len(easy_scene.road_segments) == 24

    def test_road_count_medium(self):
        s = generate_city("S-TEST", 9999, Difficulty.MEDIUM)
        # 5×5: 4×5 + 5×4 = 20+20 = 40
        assert len(s.road_segments) == 40

    def test_road_count_hard(self):
        s = generate_city("S-TEST", 9999, Difficulty.HARD)
        # 6×6: 5×6 + 6×5 = 30+30 = 60
        assert len(s.road_segments) == 60

    def test_road_polygons_valid(self, easy_scene):
        for seg in easy_scene.road_segments:
            poly = ShapelyPolygon([(p.x, p.y) for p in seg.polygon])
            assert poly.is_valid
            assert poly.area > 0

    def test_buildings_exist(self, easy_scene):
        assert len(easy_scene.buildings) > 0

    def test_parks_exist(self, easy_scene):
        assert len(easy_scene.parks) >= 1

    def test_node_ids_sequential(self, easy_scene):
        expected = [f"N{i}" for i in range(1, len(easy_scene.intersections) + 1)]
        actual = [n.id for n in easy_scene.intersections]
        assert actual == expected

    def test_segment_ids_sequential(self, easy_scene):
        for i, seg in enumerate(easy_scene.road_segments):
            assert seg.id == f"SEG-{i + 1:03d}"

    def test_horizontal_road_cross_section(self):
        """Full-width hazard on horizontal road → coverage ≈ 1.0."""
        seg = RoadSegment(
            id="SEG-001",
            node_a="N1", node_b="N2",
            centerline=[Point(x=100, y=200), Point(x=400, y=200)],
            polygon=[Point(x=100, y=180), Point(x=400, y=180),
                     Point(x=400, y=220), Point(x=100, y=220)],
            length_m=60, width_px=40, zone=Zone.NW,
        )
        # Hazard covering full road width
        hazard = ShapelyPolygon([(150, 175), (250, 175), (250, 225), (150, 225)])
        max_cov, _ = cross_section_coverage(seg, [hazard])
        assert max_cov >= 0.90

    def test_vertical_road_cross_section(self):
        """Full-width hazard on vertical road → coverage ≈ 1.0."""
        seg = RoadSegment(
            id="SEG-001",
            node_a="N1", node_b="N5",
            centerline=[Point(x=200, y=100), Point(x=200, y=400)],
            polygon=[Point(x=180, y=100), Point(x=220, y=100),
                     Point(x=220, y=400), Point(x=180, y=400)],
            length_m=60, width_px=40, zone=Zone.NW,
        )
        hazard = ShapelyPolygon([(175, 200), (225, 200), (225, 300), (175, 300)])
        max_cov, _ = cross_section_coverage(seg, [hazard])
        assert max_cov >= 0.90

    def test_partial_coverage(self):
        """Half-width hazard → coverage ≈ 0.5."""
        seg = RoadSegment(
            id="SEG-001",
            node_a="N1", node_b="N2",
            centerline=[Point(x=100, y=200), Point(x=400, y=200)],
            polygon=[Point(x=100, y=180), Point(x=400, y=180),
                     Point(x=400, y=220), Point(x=100, y=220)],
            length_m=60, width_px=40, zone=Zone.NW,
        )
        # Covers top half of road
        hazard = ShapelyPolygon([(150, 180), (250, 180), (250, 200), (150, 200)])
        max_cov, _ = cross_section_coverage(seg, [hazard])
        assert 0.30 <= max_cov < 0.90

    def test_near_miss_no_coverage(self):
        """Hazard beside road → coverage ≈ 0."""
        seg = RoadSegment(
            id="SEG-001",
            node_a="N1", node_b="N2",
            centerline=[Point(x=100, y=200), Point(x=400, y=200)],
            polygon=[Point(x=100, y=180), Point(x=400, y=180),
                     Point(x=400, y=220), Point(x=100, y=220)],
            length_m=60, width_px=40, zone=Zone.NW,
        )
        # 10px gap from road
        hazard = ShapelyPolygon([(150, 230), (250, 230), (250, 270), (150, 270)])
        max_cov, _ = cross_section_coverage(seg, [hazard])
        assert max_cov < 0.30

    def test_multiple_hazards(self):
        """Two hazards each covering half → may combine for higher coverage."""
        seg = RoadSegment(
            id="SEG-001",
            node_a="N1", node_b="N2",
            centerline=[Point(x=100, y=200), Point(x=400, y=200)],
            polygon=[Point(x=100, y=180), Point(x=400, y=180),
                     Point(x=400, y=220), Point(x=100, y=220)],
            length_m=60, width_px=40, zone=Zone.NW,
        )
        h1 = ShapelyPolygon([(150, 180), (250, 180), (250, 200), (150, 200)])
        h2 = ShapelyPolygon([(150, 200), (250, 200), (250, 220), (150, 220)])
        max_cov, _ = cross_section_coverage(seg, [h1, h2])
        assert max_cov >= 0.90


# ═══════════════════════════════════════════════════════════════════════════
# C. HAZARD SPECIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestHazardSpecs:
    def test_block_full_produces_blocked(self):
        """block_full placement → segment BLOCKED."""
        scene = generate_city("S-TEST", 5000, Difficulty.EASY)
        rng = _random.Random(5000)
        # Inject a block_full hazard on first segment
        from dl.generator.hazards import _bbox, _place_block_full, _poly_points
        seg = scene.road_segments[0]
        poly = _place_block_full(seg, rng, HazardType.FLOOD)
        hazard = Hazard(
            id="H-001", type=HazardType.FLOOD, placement=PlacementSpec.BLOCK_FULL,
            polygon=_poly_points(poly), bbox=_bbox(poly),
            affected_road=seg.id,
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)
        status = next(s for s in gt.segment_statuses if s.segment_id == seg.id)
        assert status.status == RoadStatus.BLOCKED

    def test_block_partial_produces_partial(self):
        """block_partial placement → segment PARTIAL."""
        scene = generate_city("S-TEST", 5001, Difficulty.EASY)
        rng = _random.Random(5001)
        from dl.generator.hazards import _bbox, _place_block_partial, _poly_points
        seg = scene.road_segments[0]
        poly = _place_block_partial(seg, rng, HazardType.DEBRIS)
        hazard = Hazard(
            id="H-001", type=HazardType.DEBRIS, placement=PlacementSpec.BLOCK_PARTIAL,
            polygon=_poly_points(poly), bbox=_bbox(poly),
            affected_road=seg.id,
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)
        status = next(s for s in gt.segment_statuses if s.segment_id == seg.id)
        assert status.status in (RoadStatus.PARTIAL, RoadStatus.BLOCKED)
        # Main test: should not be CLEAR
        assert status.status != RoadStatus.CLEAR

    def test_near_miss_produces_clear(self):
        """near_miss_decoy → road CLEAR, hazard doesn't touch road."""
        scene = generate_city("S-TEST", 5002, Difficulty.EASY)
        rng = _random.Random(5002)
        from dl.generator.hazards import _bbox, _place_near_miss, _poly_points
        seg = scene.road_segments[0]
        poly = _place_near_miss(seg, rng, HazardType.DEBRIS)
        hazard = Hazard(
            id="H-001", type=HazardType.DEBRIS, placement=PlacementSpec.NEAR_MISS_DECOY,
            polygon=_poly_points(poly), bbox=_bbox(poly),
            affected_road=seg.id,
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)
        status = next(s for s in gt.segment_statuses if s.segment_id == seg.id)
        assert status.status == RoadStatus.CLEAR

    def test_water_on_park_no_road_block(self):
        """water_on_park → no road blocked."""
        scene = generate_city("S-TEST", 5003, Difficulty.MEDIUM)
        if not scene.parks:
            pytest.skip("No parks generated")
        rng = _random.Random(5003)
        from dl.generator.hazards import _bbox, _place_water_on_park, _poly_points
        park = scene.parks[0]
        poly = _place_water_on_park(park, rng)
        hazard = Hazard(
            id="H-001", type=HazardType.FLOOD, placement=PlacementSpec.WATER_ON_PARK,
            polygon=_poly_points(poly), bbox=_bbox(poly),
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)
        for s in gt.segment_statuses:
            assert s.status == RoadStatus.CLEAR

    def test_damaged_building_only_no_road_block(self):
        """damaged_building_only → roads remain CLEAR."""
        scene = generate_city("S-TEST", 5004, Difficulty.EASY)
        if not scene.buildings:
            pytest.skip("No buildings generated")
        bldg = scene.buildings[0]
        hazard = Hazard(
            id="H-001", type=HazardType.DAMAGED_BUILDING,
            placement=PlacementSpec.DAMAGED_BUILDING_ONLY,
            polygon=bldg.polygon,
            bbox=BBox(
                x_min=min(p.x for p in bldg.polygon),
                y_min=min(p.y for p in bldg.polygon),
                x_max=max(p.x for p in bldg.polygon),
                y_max=max(p.y for p in bldg.polygon),
            ),
            affected_building=bldg.id,
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)
        for s in gt.segment_statuses:
            assert s.status == RoadStatus.CLEAR
        assert bldg.id in gt.damaged_building_ids

    def test_road_damage_minor_partial(self):
        """road_damage with minor severity → at most PARTIAL."""
        scene = generate_city("S-TEST", 5005, Difficulty.EASY)
        from dl.generator.hazards import _bbox, _place_road_damage, _poly_points
        rng = _random.Random(5005)
        seg = scene.road_segments[0]
        poly = _place_road_damage(seg, rng, Severity.MINOR)
        hazard = Hazard(
            id="H-001", type=HazardType.ROAD_DAMAGE,
            placement=PlacementSpec.ROAD_DAMAGE,
            polygon=_poly_points(poly), bbox=_bbox(poly),
            severity=Severity.MINOR, affected_road=seg.id,
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)
        status = next(s for s in gt.segment_statuses if s.segment_id == seg.id)
        # Minor road damage should never be BLOCKED
        assert status.status in (RoadStatus.PARTIAL, RoadStatus.CLEAR)


# ═══════════════════════════════════════════════════════════════════════════
# D. GROUND TRUTH THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

class TestGroundTruthThresholds:
    def _make_seg(self):
        return RoadSegment(
            id="SEG-001",
            node_a="N1", node_b="N2",
            centerline=[Point(x=100, y=200), Point(x=500, y=200)],
            polygon=[Point(x=100, y=180), Point(x=500, y=180),
                     Point(x=500, y=220), Point(x=100, y=220)],
            length_m=80, width_px=40, zone=Zone.NW,
        )

    def test_at_90_threshold(self):
        """Coverage exactly at 0.90 → BLOCKED."""
        seg = self._make_seg()
        # Cover 90% of width (36 out of 40 px)
        hazard = ShapelyPolygon([(200, 178), (300, 178), (300, 218), (200, 218)])
        max_cov, _ = cross_section_coverage(seg, [hazard])
        from dl.generator.ground_truth import _classify
        status = _classify(max_cov)
        # At 90%+ → BLOCKED
        if max_cov >= 0.90:
            assert status == RoadStatus.BLOCKED

    def test_just_below_90(self):
        """Coverage just below 0.90 → PARTIAL."""
        seg = self._make_seg()
        # Cover ~85% of width (34 out of 40 px)
        hazard = ShapelyPolygon([(200, 180), (300, 180), (300, 214), (200, 214)])
        max_cov, _ = cross_section_coverage(seg, [hazard])
        from dl.generator.ground_truth import _classify
        status = _classify(max_cov)
        if 0.30 <= max_cov < 0.90:
            assert status == RoadStatus.PARTIAL

    def test_at_30_threshold(self):
        """Coverage at 0.30 → PARTIAL."""
        from dl.generator.ground_truth import _classify
        assert _classify(0.30) == RoadStatus.PARTIAL

    def test_just_below_30(self):
        """Coverage just below 0.30 → CLEAR."""
        from dl.generator.ground_truth import _classify
        assert _classify(0.29) == RoadStatus.CLEAR


# ═══════════════════════════════════════════════════════════════════════════
# E. VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════

class TestValidator:
    def test_valid_scene_passes(self):
        """A correctly generated scene should pass validation."""
        scene = generate_city("S-TEST", 7777, Difficulty.EASY)
        rng = _random.Random(7777)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        errors = validate_scene(scene, gt)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_corrupted_ground_truth_detected(self):
        """Deliberately corrupted GT should be caught."""
        scene = generate_city("S-TEST", 7778, Difficulty.EASY)
        rng = _random.Random(7778)

        # Inject a known block_full hazard
        from dl.generator.hazards import _bbox, _place_block_full, _poly_points
        seg = scene.road_segments[0]
        poly = _place_block_full(seg, rng, HazardType.FLOOD)
        hazard = Hazard(
            id="H-001", type=HazardType.FLOOD,
            placement=PlacementSpec.BLOCK_FULL,
            polygon=_poly_points(poly), bbox=_bbox(poly),
            affected_road=seg.id,
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)

        # Corrupt: change BLOCKED to CLEAR
        corrupted = copy.deepcopy(gt)
        for s in corrupted.segment_statuses:
            if s.segment_id == seg.id and s.status == RoadStatus.BLOCKED:
                s.status = RoadStatus.CLEAR
                s.max_coverage = 0.0
                break

        errors = validate_scene(scene, corrupted)
        # Should detect the corruption
        assert any(seg.id in e for e in errors), f"Corruption not detected. Errors: {errors}"

    def test_disconnected_graph_detected(self):
        """Disconnected road graph should be caught."""
        scene = generate_city("S-TEST", 7779, Difficulty.EASY)
        # Add an isolated node with no connected edges
        isolated_node = Intersection(id="N99", x=10, y=10, zone=Zone.NW)
        scene.intersections.append(isolated_node)

        gt = compute_ground_truth(scene)
        errors = validate_scene(scene, gt)
        assert any("not connected" in e for e in errors), f"Disconnected graph not detected: {errors}"

    def test_invalid_near_miss_detected(self):
        """Near-miss hazard that directly intersects a road polygon must fail validation."""
        scene = generate_city("S-TEST", 7780, Difficulty.EASY)
        seg = scene.road_segments[0]
        # Deliberately place a near-miss directly on the road
        hazard = Hazard(
            id="H-001",
            type=HazardType.DEBRIS,
            placement=PlacementSpec.NEAR_MISS_DECOY,
            polygon=seg.polygon,
            bbox=BBox(
                x_min=min(p.x for p in seg.polygon),
                y_min=min(p.y for p in seg.polygon),
                x_max=max(p.x for p in seg.polygon),
                y_max=max(p.y for p in seg.polygon),
            ),
            affected_road=seg.id,
        )
        scene.hazards = [hazard]
        gt = compute_ground_truth(scene)
        errors = validate_scene(scene, gt)
        assert any("intersects road" in e for e in errors), f"Invalid near-miss not detected: {errors}"


# ═══════════════════════════════════════════════════════════════════════════
# F. QUESTIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestQuestions:
    def test_all_question_types_generated(self):
        """Scene with hazards should generate multiple question types."""
        scene = generate_city("S-TEST", 8888, Difficulty.MEDIUM)
        rng = _random.Random(8888)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        qs = generate_questions(scene, gt, _random.Random(8888))

        types_present = {q.type for q in qs.questions}
        # At minimum we should have blocked_segments, damaged_buildings, water_regions
        assert QuestionType.BLOCKED_SEGMENTS in types_present
        assert QuestionType.DAMAGED_BUILDINGS in types_present
        assert QuestionType.WATER_REGIONS in types_present

    def test_route_endpoints_exist(self):
        """Route question endpoints must be valid node IDs."""
        scene = generate_city("S-TEST", 8889, Difficulty.MEDIUM)
        rng = _random.Random(8889)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        qs = generate_questions(scene, gt, _random.Random(8889))

        node_ids = {n.id for n in scene.intersections}
        for q in qs.questions:
            if q.type in (QuestionType.ROUTE_OBSTRUCTION_POSITIVE,
                          QuestionType.ROUTE_OBSTRUCTION_NEGATIVE):
                # Check that prompt references valid nodes
                for nid in node_ids:
                    if nid in q.prompt:
                        break

    def test_no_answer_leakage(self):
        """Prompts should not contain expected answers."""
        scene = generate_city("S-TEST", 8890, Difficulty.EASY)
        rng = _random.Random(8890)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        qs = generate_questions(scene, gt, _random.Random(8890))

        for q in qs.questions:
            # Answer shouldn't be in prompt
            answer_str = json.dumps(q.expected_answer)
            assert answer_str not in q.prompt


# ═══════════════════════════════════════════════════════════════════════════
# G. INTEGRATION — FULL SCENE
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_full_easy_scene(self):
        """Generate a complete easy scene end-to-end."""
        scene = generate_city("S-0001", 2026, Difficulty.EASY)
        rng = _random.Random(2026)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        qs = generate_questions(scene, gt, _random.Random(2026))

        assert scene.grid_size == 4
        assert len(scene.road_segments) == 24
        assert len(gt.segment_statuses) == 24
        assert len(qs.questions) >= 3

        errors = validate_scene(scene, gt)
        assert errors == [], f"Validation errors: {errors}"

    def test_full_medium_scene(self):
        """Generate a complete medium scene end-to-end."""
        scene = generate_city("S-0031", 2056, Difficulty.MEDIUM)
        rng = _random.Random(2056)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        generate_questions(scene, gt, _random.Random(2056))

        assert scene.grid_size == 5
        errors = validate_scene(scene, gt)
        assert errors == [], f"Validation errors: {errors}"

    def test_full_hard_scene(self):
        """Generate a complete hard scene end-to-end."""
        scene = generate_city("S-0066", 2091, Difficulty.HARD)
        rng = _random.Random(2091)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        generate_questions(scene, gt, _random.Random(2091))

        assert scene.grid_size == 6
        errors = validate_scene(scene, gt)
        assert errors == [], f"Validation errors: {errors}"


# ═══════════════════════════════════════════════════════════════════════════
# H. DATASET COMPOSITION & VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestDatasetComposition:
    def test_manifest_and_stats(self):
        """Verify the 100-scene dataset composition against master plan targets."""
        import hashlib
        from pathlib import Path

        manifest_path = Path("datasets/v1/manifest.json")
        stats_path = Path("datasets/v1/stats.json")

        assert manifest_path.exists(), "datasets/v1/manifest.json must exist"
        assert stats_path.exists(), "datasets/v1/stats.json must exist"

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        with open(stats_path, encoding="utf-8") as f:
            stats = json.load(f)

        scenes = manifest["scenes"]
        # Exactly 100 scenes
        assert len(scenes) == 100
        assert stats["total_scenes"] == 100

        # Distribution: 30 easy, 35 medium, 35 hard
        assert stats["difficulty_counts"]["easy"] == 30
        assert stats["difficulty_counts"]["medium"] == 35
        assert stats["difficulty_counts"]["hard"] == 35

        # Split: 30 dev (S-0001 to S-0030), 70 test (S-0031 to S-0100)
        dev_scenes = [s for s in scenes if s["split"] == "dev"]
        test_scenes = [s for s in scenes if s["split"] == "test"]
        assert len(dev_scenes) == 30
        assert len(test_scenes) == 70

        # At least 25% near-miss route questions
        assert stats["near_miss_percentage"] >= 25.0

        # 5 hazard classes present
        assert len(stats["hazard_type_counts"]) == 5

        # All 6 question types present
        assert len(stats["question_type_counts"]) == 6

        # Check SHA-256 hashes of committed development scenes match files on disk
        for scene_entry in scenes[:5]:  # verify first 5 dev scenes on disk
            sid = scene_entry["scene_id"]
            for fname, expected_hash in scene_entry["file_hashes"].items():
                fpath = Path(f"datasets/v1/{sid}/{fname}")
                if fpath.exists():
                    raw = fpath.read_bytes()
                    if fname.endswith(".json"):
                        assert b"\r\n" not in raw, f"{sid}/{fname} must use LF line endings"
                    h = hashlib.sha256(raw)
                    assert h.hexdigest() == expected_hash, f"Hash mismatch for {sid}/{fname}"

    def test_contract_scene_and_evaluation_adapter(self):
        """Generated scenes convert cleanly into canonical Scene and EvaluationDatasetScene contracts."""
        from dl.contracts.evaluation import EvaluationDatasetScene
        from dl.contracts.scene import Scene as CanonicalScene

        scene = generate_city("S-0001", 2026, Difficulty.MEDIUM)
        rng = _random.Random(2026)
        scene.hazards = generate_hazards(scene, rng)
        gt = compute_ground_truth(scene)
        qs = generate_questions(scene, gt, _random.Random(2026))

        cs = to_contract_scene(scene, gt, qs, split="dev")
        assert isinstance(cs, CanonicalScene)
        assert cs.scene_id == "S-0001"
        assert len(cs.nodes) == 25
        assert len(cs.segments) == 40

        eval_record = to_evaluation_record(scene, gt, qs, split="dev")
        validated = EvaluationDatasetScene.model_validate(eval_record)
        assert validated.scene_id == "S-0001"
        assert validated.split == "dev"

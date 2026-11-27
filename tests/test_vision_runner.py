"""
tests/test_vision_runner.py
---------------------------
Unit and integration tests for dl/vision/runner.py.

Tests cover:
  - CLI argument parsing
  - Dataset discovery (discover_scenes)
  - SceneLoader — raw → contract translation
  - Prediction output validation
  - Resume / skip behaviour
  - Failure handling and exponential back-off
  - Run-log creation
  - Worker pool execution (run_batch)
  - Quota-error stop

No real API calls are made.  All scenes are hand-crafted in temporary
directories.  The real dataset (datasets/v1/S-0001) is never modified.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dl.contracts.enums import Difficulty, HazardType, RoadStatus
from dl.contracts.scene import Box, GroundTruth, RoadNode, RoadSegment, Scene
from dl.contracts.vision import SceneAnalysis, SegmentVerdict
from dl.vision.runner import (
    RunLog,
    SceneResult,
    SceneLoader,
    _bbox_dict_to_box,
    _build_arg_parser,
    _haz_type,
    _is_quota_error,
    _process_one_scene,
    _save_run_log,
    _xy_list_to_tuples,
    already_done,
    discover_scenes,
    prediction_path,
    run_batch,
    save_prediction,
)


# ---------------------------------------------------------------------------
# Shared fixture builders
# ---------------------------------------------------------------------------

def _minimal_scene_json() -> dict:
    """Minimal raw scene.json content matching the actual dataset format."""
    return {
        "scene_id": "S-TEST",
        "difficulty": "easy",
        "seed": 1,
        "image_width": 512,
        "image_height": 512,
        "intersections": [
            {"id": "N1", "x": 0.0, "y": 0.0, "zone": "NW"},
            {"id": "N2", "x": 100.0, "y": 0.0, "zone": "NW"},
        ],
        "road_segments": [
            {
                "id": "SEG-001",
                "node_a": "N1",
                "node_b": "N2",
                "length_m": 100.0,
                "width_px": 20.0,
                "zone": "NW",
                "centerline": [{"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 0.0}],
                "polygon": [
                    {"x": 0.0, "y": -10.0},
                    {"x": 100.0, "y": -10.0},
                    {"x": 100.0, "y": 10.0},
                    {"x": 0.0, "y": 10.0},
                ],
            }
        ],
        "hazards": [
            {
                "id": "H-001",
                "type": "debris",
                "placement": "block_full",
                "affected_road": "SEG-001",
                "affected_building": None,
                "severity": None,
                "bbox": {"x_min": 40.0, "y_min": -10.0, "x_max": 60.0, "y_max": 10.0},
                "polygon": [
                    {"x": 40.0, "y": -10.0},
                    {"x": 60.0, "y": -10.0},
                    {"x": 60.0, "y": 10.0},
                    {"x": 40.0, "y": 10.0},
                ],
            }
        ],
        "buildings": [],
        "parks": [],
        "grid_size": 5,
        "pixel_to_metre": 1.0,
    }


def _minimal_gt_json(seg_id: str = "SEG-001", status: str = "BLOCKED") -> dict:
    """Minimal raw ground_truth.json content."""
    return {
        "scene_id": "S-TEST",
        "segment_statuses": [
            {"segment_id": seg_id, "status": status, "max_coverage": 1.0, "blocking_hazards": ["H-001"]},
        ],
        "damaged_building_ids": [],
        "water_region_ids": [],
        "hazard_area_per_zone": {"NW": 0.0, "NE": 0.0, "SW": 0.0, "SE": 0.0},
    }


def _make_fake_png() -> bytes:
    """Return a 1-pixel valid-enough PNG for testing (not a real image)."""
    # Minimal PNG: signature + IHDR + IDAT + IEND
    # Using a known minimal valid PNG (1×1 white pixel)
    import base64
    b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    return base64.b64decode(b64)


def _minimal_questions_json() -> dict:
    return {
        "scene_id": "S-TEST",
        "questions": [
            {
                "id": "Q-001",
                "type": "route_obstruction_positive",
                "prompt": "Is route A-B blocked?",
                "expected_answer": {"obstructed": True},
            },
            {
                "id": "Q-002",
                "type": "blocked_segments",
                "prompt": "Which segments are blocked?",
                "expected_answer": {},
            },
        ],
    }


def _create_scene_dir(root: Path, scene_id: str = "S-TEST") -> Path:
    """Write all required files for a minimal scene into a temp directory."""
    sd = root / scene_id
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "scene.json").write_text(json.dumps(_minimal_scene_json()), encoding="utf-8")
    (sd / "ground_truth.json").write_text(json.dumps(_minimal_gt_json()), encoding="utf-8")
    (sd / "questions.json").write_text(json.dumps(_minimal_questions_json()), encoding="utf-8")
    (sd / "image_plain.png").write_bytes(_make_fake_png())
    (sd / "image_labelled.png").write_bytes(_make_fake_png())
    return sd


def _make_analysis(scene_id: str = "S-TEST") -> SceneAnalysis:
    return SceneAnalysis(
        scene_id=scene_id,
        hazards=[],
        segment_verdicts={
            "SEG-001": SegmentVerdict(
                status=RoadStatus.CLEAR,
                confidence=0.75,
                evidence="test",
                visible=True,
            )
        },
        damaged_building_count=None,
        water_regions=[],
        image_quality_good=None,
        model_id="oracle-mock",
        prompt_version="v1",
        valid_json=True,
        latency_ms=10,
    )


# ===========================================================================
# 1. CLI argument parser
# ===========================================================================

class TestArgParser:

    def test_defaults(self):
        parser = _build_arg_parser()
        args = parser.parse_args([])
        assert args.split == "dev"
        assert args.model == "mock"
        assert args.prompt_version == "v1"
        assert args.image_variant == "plain"
        assert args.workers == 3
        assert args.no_cache is False

    def test_split_choices(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--split", "test"])
        assert args.split == "test"

    def test_invalid_split_rejected(self):
        parser = _build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--split", "train"])

    def test_model_flag(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--model", "always-clear"])
        assert args.model == "always-clear"

    def test_prompt_version_flag(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--prompt-version", "v2"])
        assert args.prompt_version == "v2"

    def test_image_variant_flag(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--image-variant", "labelled"])
        assert args.image_variant == "labelled"

    def test_no_cache_flag(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--no-cache"])
        assert args.no_cache is True

    def test_workers_flag(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--workers", "5"])
        assert args.workers == 5

    def test_dataset_flag(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--dataset", "/some/path"])
        # Use Path comparison to handle Windows/POSIX separator differences
        assert args.dataset == Path("/some/path")

    def test_output_flag(self):
        parser = _build_arg_parser()
        args = parser.parse_args(["--output", "/out"])
        assert args.output == Path("/out")


# ===========================================================================
# 2. Dataset discovery
# ===========================================================================

class TestDiscoverScenes:

    def test_finds_scene_dirs(self, tmp_path: Path):
        _create_scene_dir(tmp_path, "S-001")
        _create_scene_dir(tmp_path, "S-002")
        scenes = discover_scenes(tmp_path, "dev")
        assert len(scenes) == 2
        assert {s.name for s in scenes} == {"S-001", "S-002"}

    def test_returns_sorted(self, tmp_path: Path):
        _create_scene_dir(tmp_path, "S-003")
        _create_scene_dir(tmp_path, "S-001")
        _create_scene_dir(tmp_path, "S-002")
        scenes = discover_scenes(tmp_path, "dev")
        assert [s.name for s in scenes] == ["S-001", "S-002", "S-003"]

    def test_missing_dataset_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Dataset directory not found"):
            discover_scenes(tmp_path / "nonexistent", "dev")

    def test_ignores_dirs_without_scene_json(self, tmp_path: Path):
        _create_scene_dir(tmp_path, "S-001")
        # Dir without scene.json
        (tmp_path / "not_a_scene").mkdir()
        scenes = discover_scenes(tmp_path, "dev")
        assert len(scenes) == 1

    def test_empty_dataset_returns_empty_list(self, tmp_path: Path):
        scenes = discover_scenes(tmp_path, "dev")
        assert scenes == []


# ===========================================================================
# 3. SceneLoader — raw → contract translation
# ===========================================================================

class TestSceneLoader:

    def test_load_scene_produces_valid_scene(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        loader = SceneLoader(sd, split="dev")
        scene = loader.load_scene()

        assert isinstance(scene, Scene)
        assert scene.scene_id == "S-TEST"
        assert scene.split == "dev"
        assert len(scene.nodes) == 2
        assert len(scene.segments) == 1
        assert scene.segments[0].segment_id == "SEG-001"
        assert scene.segments[0].from_node == "N1"
        assert scene.segments[0].to_node == "N2"

    def test_load_scene_hazards(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        loader = SceneLoader(sd, split="dev")
        scene = loader.load_scene()
        assert len(scene.hazards) == 1
        assert scene.hazards[0].hazard_id == "H-001"
        assert scene.hazards[0].type == HazardType.DEBRIS

    def test_load_scene_ground_truth_blocked(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        loader = SceneLoader(sd, split="dev")
        scene = loader.load_scene()
        # ground_truth.json has SEG-001 as BLOCKED
        assert scene.ground_truth.segment_status.get("SEG-001") == "blocked"

    def test_ground_truth_clear_lowercased(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        # Override ground_truth to CLEAR
        (sd / "ground_truth.json").write_text(
            json.dumps(_minimal_gt_json("SEG-001", "CLEAR")), encoding="utf-8"
        )
        loader = SceneLoader(sd, split="dev")
        scene = loader.load_scene()
        assert scene.ground_truth.segment_status["SEG-001"] == "clear"

    def test_load_image_plain(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        loader = SceneLoader(sd, split="dev")
        img = loader.load_image("plain")
        assert isinstance(img, bytes)
        assert len(img) > 0

    def test_load_image_labelled(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        loader = SceneLoader(sd, split="dev")
        img = loader.load_image("labelled")
        assert isinstance(img, bytes)

    def test_load_image_missing_raises(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        (sd / "image_plain.png").unlink()
        loader = SceneLoader(sd, split="dev")
        with pytest.raises(FileNotFoundError, match="image_plain.png"):
            loader.load_image("plain")

    def test_load_questions_route_only(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        loader = SceneLoader(sd, split="dev")
        qs = loader.load_questions()
        # Only route_obstruction_* questions are returned
        assert "Q-001" in qs
        assert "Q-002" not in qs  # type=blocked_segments, not route

    def test_split_injected_correctly(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path, "S-TEST")
        for split in ("dev", "test"):
            loader = SceneLoader(sd, split=split)
            scene = loader.load_scene()
            assert scene.split == split

    def test_bbox_dict_to_box(self):
        box = _bbox_dict_to_box({"x_min": 1.0, "y_min": 2.0, "x_max": 3.0, "y_max": 4.0})
        assert box.root == (1.0, 2.0, 3.0, 4.0)

    def test_xy_list_to_tuples(self):
        pts = _xy_list_to_tuples([{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}])
        assert pts == [(1.0, 2.0), (3.0, 4.0)]

    def test_haz_type_debris(self):
        assert _haz_type("debris") == HazardType.DEBRIS

    def test_haz_type_case_insensitive(self):
        assert _haz_type("FLOOD") == HazardType.FLOOD
        assert _haz_type("Fallen_Tree") == HazardType.FALLEN_TREE


# ===========================================================================
# 4. Output helpers
# ===========================================================================

class TestOutputHelpers:

    def test_prediction_path(self, tmp_path: Path):
        p = prediction_path(tmp_path, "S-0001")
        assert p == tmp_path / "S-0001_prediction.json"

    def test_already_done_false_before_save(self, tmp_path: Path):
        assert already_done(tmp_path, "S-0001") is False

    def test_already_done_true_after_save(self, tmp_path: Path):
        analysis = _make_analysis("S-0001")
        save_prediction(tmp_path, analysis)
        assert already_done(tmp_path, "S-0001") is True

    def test_save_prediction_writes_valid_json(self, tmp_path: Path):
        analysis = _make_analysis("S-0001")
        path = save_prediction(tmp_path, analysis)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["scene_id"] == "S-0001"
        assert data["model_id"] == "oracle-mock"
        assert "segment_verdicts" in data

    def test_save_prediction_creates_output_dir(self, tmp_path: Path):
        out = tmp_path / "deep" / "nested"
        analysis = _make_analysis("S-X")
        save_prediction(out, analysis)
        assert (out / "S-X_prediction.json").exists()

    def test_saved_prediction_validates_as_contract(self, tmp_path: Path):
        analysis = _make_analysis("S-V")
        path = save_prediction(tmp_path, analysis)
        raw = path.read_text(encoding="utf-8")
        reloaded = SceneAnalysis.model_validate_json(raw)
        assert reloaded.scene_id == "S-V"


# ===========================================================================
# 5. Quota error detection
# ===========================================================================

class TestIsQuotaError:

    def test_quota_keyword(self):
        assert _is_quota_error(Exception("RESOURCE_EXHAUSTED: quota exceeded")) is True

    def test_403_keyword(self):
        assert _is_quota_error(Exception("HTTP 403 Forbidden")) is True

    def test_401_keyword(self):
        assert _is_quota_error(Exception("401 UNAUTHENTICATED")) is True

    def test_non_quota_error(self):
        assert _is_quota_error(Exception("FileNotFoundError: missing file")) is False

    def test_timeout_not_quota(self):
        assert _is_quota_error(TimeoutError("connection timed out")) is False


# ===========================================================================
# 6. Run log
# ===========================================================================

class TestRunLog:

    def test_save_run_log_writes_json(self, tmp_path: Path):
        log = RunLog(
            run_id="run_test",
            model="mock",
            prompt_version="v1",
            image_variant="plain",
            split="dev",
            dataset_dir="/data",
            output_dir=str(tmp_path),
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
            total_scenes=1,
            processed=1,
            skipped=0,
            failed=0,
            scenes=[SceneResult(scene_id="S-001", status="ok", latency_ms=50, valid_json=True)],
        )
        path = _save_run_log(tmp_path, log)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["run_id"] == "run_test"
        assert data["total_scenes"] == 1
        assert data["scenes"][0]["scene_id"] == "S-001"
        assert data["scenes"][0]["status"] == "ok"


# ===========================================================================
# 7. _process_one_scene — single-scene processing
# ===========================================================================

class TestProcessOneScene:

    def test_ok_produces_prediction_file(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path / "ds", "S-TEST")
        out = tmp_path / "out"
        out.mkdir()

        # Use the always-clear baseline — no API calls
        from dl.vision.baselines import AlwaysClearBaseline
        adapter = AlwaysClearBaseline()

        result = _process_one_scene(
            scene_dir=sd,
            adapter=adapter,
            split="dev",
            image_variant="plain",
            prompt_version="v1",
            output_dir=out,
        )

        assert result.status == "ok"
        assert result.valid_json is True
        assert result.latency_ms is not None and result.latency_ms >= 0
        assert prediction_path(out, "S-TEST").exists()

    def test_skip_when_already_done(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path / "ds", "S-TEST")
        out = tmp_path / "out"
        out.mkdir()

        # Pre-create a prediction file
        analysis = _make_analysis("S-TEST")
        save_prediction(out, analysis)

        adapter = MagicMock()
        result = _process_one_scene(
            scene_dir=sd,
            adapter=adapter,
            split="dev",
            image_variant="plain",
            prompt_version="v1",
            output_dir=out,
        )

        assert result.status == "skipped"
        adapter.analyze_scene.assert_not_called()

    def test_failed_on_adapter_error(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path / "ds", "S-TEST")
        out = tmp_path / "out"
        out.mkdir()

        adapter = MagicMock()
        adapter.analyze_scene.side_effect = RuntimeError("adapter broke")

        result = _process_one_scene(
            scene_dir=sd,
            adapter=adapter,
            split="dev",
            image_variant="plain",
            prompt_version="v1",
            output_dir=out,
        )

        assert result.status == "failed"
        assert "adapter broke" in (result.error or "")

    def test_quota_error_stops_immediately(self, tmp_path: Path):
        sd = _create_scene_dir(tmp_path / "ds", "S-TEST")
        out = tmp_path / "out"
        out.mkdir()

        adapter = MagicMock()
        adapter.analyze_scene.side_effect = RuntimeError("HTTP 403 quota exceeded")

        result = _process_one_scene(
            scene_dir=sd,
            adapter=adapter,
            split="dev",
            image_variant="plain",
            prompt_version="v1",
            output_dir=out,
        )

        assert result.status == "quota_stop"
        # Only 1 call — no retries on quota errors
        adapter.analyze_scene.assert_called_once()


# ===========================================================================
# 8. run_batch — full batch execution
# ===========================================================================

class TestRunBatch:

    def test_run_batch_mock_produces_log(self, tmp_path: Path):
        ds = tmp_path / "ds"
        _create_scene_dir(ds, "S-001")
        out = tmp_path / "out"

        log = run_batch(
            dataset_dir=ds,
            split="dev",
            model="always-clear",
            prompt_version="v1",
            image_variant="plain",
            output_dir=out,
            workers=1,
            use_cache=False,
        )

        assert isinstance(log, RunLog)
        assert log.total_scenes == 1
        assert log.processed == 1
        assert log.failed == 0
        assert log.skipped == 0

    def test_run_batch_writes_prediction_file(self, tmp_path: Path):
        ds = tmp_path / "ds"
        _create_scene_dir(ds, "S-001")
        out = tmp_path / "out"

        run_batch(
            dataset_dir=ds,
            split="dev",
            model="always-clear",
            output_dir=out,
            workers=1,
            use_cache=False,
        )

        assert prediction_path(out, "S-001").exists()

    def test_run_batch_writes_run_log_file(self, tmp_path: Path):
        ds = tmp_path / "ds"
        _create_scene_dir(ds, "S-001")
        out = tmp_path / "out"

        log = run_batch(
            dataset_dir=ds,
            split="dev",
            model="always-clear",
            output_dir=out,
            workers=1,
            use_cache=False,
        )

        log_files = list(out.glob("*.log.json"))
        assert len(log_files) == 1

    def test_run_batch_skips_already_done_scenes(self, tmp_path: Path):
        ds = tmp_path / "ds"
        _create_scene_dir(ds, "S-001")
        out = tmp_path / "out"
        out.mkdir()

        # Pre-create prediction
        analysis = _make_analysis("S-001")
        save_prediction(out, analysis)

        log = run_batch(
            dataset_dir=ds,
            split="dev",
            model="always-clear",
            output_dir=out,
            workers=1,
            use_cache=False,
        )

        assert log.skipped == 1
        assert log.processed == 0

    def test_run_batch_multiple_scenes(self, tmp_path: Path):
        ds = tmp_path / "ds"
        for i in range(3):
            _create_scene_dir(ds, f"S-{i:03d}")
        out = tmp_path / "out"

        log = run_batch(
            dataset_dir=ds,
            split="dev",
            model="always-clear",
            output_dir=out,
            workers=2,
            use_cache=False,
        )

        assert log.total_scenes == 3
        assert log.processed == 3

    def test_run_batch_missing_dataset_returns_empty_log(self, tmp_path: Path):
        log = run_batch(
            dataset_dir=tmp_path / "nonexistent",
            split="dev",
            model="always-clear",
            output_dir=tmp_path / "out",
            workers=1,
            use_cache=False,
        )
        assert log.total_scenes == 0
        assert log.processed == 0

    def test_run_batch_with_cache(self, tmp_path: Path):
        """Cache wrapper must not break the run."""
        ds = tmp_path / "ds"
        _create_scene_dir(ds, "S-001")
        out = tmp_path / "out"

        log = run_batch(
            dataset_dir=ds,
            split="dev",
            model="always-clear",
            output_dir=out,
            workers=1,
            use_cache=True,  # Cache enabled
        )

        assert log.processed == 1
        assert prediction_path(out, "S-001").exists()

    def test_run_batch_prediction_validates_contract(self, tmp_path: Path):
        """Every saved prediction must be loadable as a valid SceneAnalysis."""
        ds = tmp_path / "ds"
        _create_scene_dir(ds, "S-001")
        out = tmp_path / "out"

        run_batch(
            dataset_dir=ds,
            split="dev",
            model="always-clear",
            output_dir=out,
            workers=1,
            use_cache=False,
        )

        pred_path = prediction_path(out, "S-001")
        raw = pred_path.read_text(encoding="utf-8")
        analysis = SceneAnalysis.model_validate_json(raw)
        assert analysis.valid_json is True
        assert analysis.model_id == "baseline-always-clear"

    def test_run_batch_failed_scene_recorded_in_log(self, tmp_path: Path):
        ds = tmp_path / "ds"
        _create_scene_dir(ds, "S-001")
        out = tmp_path / "out"

        # Patch _process_one_scene to simulate failure
        def fake_process(*args, **kwargs):
            return SceneResult(scene_id="S-001", status="failed", error="simulated")

        with patch("dl.vision.runner._process_one_scene", side_effect=fake_process):
            log = run_batch(
                dataset_dir=ds,
                split="dev",
                model="always-clear",
                output_dir=out,
                workers=1,
                use_cache=False,
            )

        assert log.failed == 1


# ===========================================================================
# 9. Real dataset smoke test (non-modifying read-only)
# ===========================================================================

class TestRealDatasetSmoke:
    """
    Read-only tests against the actual datasets/v1/S-0001 folder.

    These tests NEVER write to the dataset folder.
    If the dataset is unavailable, tests are skipped gracefully.
    """

    REAL_SCENE_DIR = Path("datasets") / "v1" / "S-0001"

    def _requires_dataset(self):
        if not self.REAL_SCENE_DIR.exists():
            pytest.skip("Real dataset not found — skipping smoke test.")

    def test_discover_one_real_scene(self):
        self._requires_dataset()
        scenes = discover_scenes(Path("datasets") / "v1", "dev")
        assert len(scenes) >= 1
        assert any(s.name == "S-0001" for s in scenes)

    def test_load_real_scene(self):
        self._requires_dataset()
        loader = SceneLoader(self.REAL_SCENE_DIR, split="dev")
        scene = loader.load_scene()
        assert scene.scene_id == "S-0001"
        assert len(scene.segments) == 24
        assert len(scene.nodes) == 16

    def test_load_real_ground_truth(self):
        self._requires_dataset()
        loader = SceneLoader(self.REAL_SCENE_DIR, split="dev")
        scene = loader.load_scene()
        gt = scene.ground_truth
        # SEG-017 is BLOCKED according to ground_truth.json
        assert gt.segment_status.get("SEG-017") == "blocked"
        # All others should be clear
        for sid, status in gt.segment_status.items():
            if sid != "SEG-017":
                assert status == "clear", f"{sid} expected clear, got {status}"

    def test_real_scene_validates_as_contract(self):
        self._requires_dataset()
        loader = SceneLoader(self.REAL_SCENE_DIR, split="dev")
        scene = loader.load_scene()
        # Pydantic validation already runs in model_validate / __init__
        assert isinstance(scene, Scene)
        assert scene.difficulty == "easy"

    def test_real_image_loads(self):
        self._requires_dataset()
        loader = SceneLoader(self.REAL_SCENE_DIR, split="dev")
        img = loader.load_image("plain")
        assert len(img) > 1000  # Must be a real PNG, not empty

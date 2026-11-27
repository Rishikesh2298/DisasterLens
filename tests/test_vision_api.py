"""
Unit tests for dl.vision.api (analyze_observation endpoint).

Tests cover:
- Mock mode execution and return structure
- Cached mode execution (cache miss, then hit)
- Live mode blocker reporting (NotImplementedError on empty provider)
- Live mode execution with registered provider
- Input variations: image as bytes, image as Path
- Zone geometry variations: Scene instance, list of RoadSegments, dict
- Returned hazards, direct verdicts, mapped verdicts, guarded final verdicts
- Metadata (model_id, prompt_version, latency)
- Invalid mode validation (ValueError)
- Attribute and dict-style access on ObservationResult
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dl.contracts.enums import Difficulty, HazardType, RoadStatus
from dl.contracts.scene import Box, GroundTruth, Hazard, RoadNode, RoadSegment, Scene
from dl.contracts.vision import PredictedHazard, SceneAnalysis, SegmentVerdict
from dl.vision.api import ObservationResult, analyze_observation
from dl.vision.base import VisionAdapter
from dl.vision.mapper import RoadMappingResult
from dl.vision.registry import clear_registry, register_adapter


def _make_sample_segment(segment_id: str = "SEG-001") -> RoadSegment:
    """Create a sample valid RoadSegment with polygon and centerline."""
    return RoadSegment(
        segment_id=segment_id,
        from_node="N1",
        to_node="N2",
        length=100.0,
        centerline=[(0.0, 50.0), (100.0, 50.0)],
        polygon=[(0.0, 40.0), (100.0, 40.0), (100.0, 60.0), (0.0, 60.0)],
    )


def _make_test_scene(segment_id: str = "SEG-001", status: str = "clear") -> Scene:
    """Create a sample Scene with ground truth for mock adapter."""
    seg = _make_sample_segment(segment_id)
    return Scene(
        scene_id="S-0001",
        difficulty=Difficulty.EASY,
        split="dev",
        seed=0,
        image_width=512,
        image_height=512,
        nodes=[RoadNode(node_id="N1", x=0.0, y=50.0), RoadNode(node_id="N2", x=100.0, y=50.0)],
        segments=[seg],
        hazards=[],
        ground_truth=GroundTruth(
            hazards=[],
            segment_status={segment_id: status},
            damaged_building_count=0,
            water_regions=[],
            route_questions={},
            zone_comparisons={},
        ),
    )


def _make_fake_png_bytes() -> bytes:
    """Minimal valid PNG bytes."""
    import base64
    b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    return base64.b64decode(b64)


# =============================================================================
# 1. Mock Mode Tests
# =============================================================================

class TestMockMode:
    """Test analyze_observation in 'mock' mode."""

    def test_mock_mode_returns_observation_result(self):
        scene = _make_test_scene("SEG-001", status="clear")
        image = _make_fake_png_bytes()

        result = analyze_observation(image=image, zone_geometry=scene, mode="mock")

        assert isinstance(result, ObservationResult)
        assert result.model_id == "oracle-mock"
        assert result.prompt_version == "v1"
        assert result.latency_ms >= 0

        # Check required return components
        assert isinstance(result.hazards, list)
        assert isinstance(result.direct_verdicts, dict)
        assert isinstance(result.mapped_verdicts, dict)
        assert isinstance(result.guarded_verdicts, dict)

        # Segment should be evaluated
        assert "SEG-001" in result.guarded_verdicts
        assert isinstance(result.guarded_verdicts["SEG-001"], SegmentVerdict)

    def test_mock_mode_blocked_road_mapped_and_guarded(self):
        seg = _make_sample_segment("SEG-001")
        hazard_box = Box((40.0, 35.0, 60.0, 65.0))  # Covers full road width
        h = Hazard(hazard_id="H-1", type=HazardType.DEBRIS, bbox=hazard_box)
        scene = Scene(
            scene_id="S-0001",
            difficulty=Difficulty.EASY,
            split="dev",
            seed=0,
            image_width=512,
            image_height=512,
            nodes=[RoadNode(node_id="N1", x=0.0, y=50.0), RoadNode(node_id="N2", x=100.0, y=50.0)],
            segments=[seg],
            hazards=[h],
            ground_truth=GroundTruth(
                hazards=[h],
                segment_status={"SEG-001": "blocked"},
                damaged_building_count=0,
                water_regions=[],
                route_questions={},
                zone_comparisons={},
            ),
        )
        image = _make_fake_png_bytes()

        result = analyze_observation(image=image, zone_geometry=scene, mode="mock")

        # Mock produces the hazard
        assert len(result.hazards) == 1
        assert result.hazards[0].type == HazardType.DEBRIS

        # Mapped verdict should be BLOCKED because hazard covers road
        assert "SEG-001" in result.mapped_verdicts
        assert result.mapped_verdicts["SEG-001"].status == RoadStatus.BLOCKED

        # Guarded verdict matches
        assert result.guarded_verdicts["SEG-001"].status == RoadStatus.BLOCKED


# =============================================================================
# 2. Cached Mode Tests
# =============================================================================

class TestCachedMode:
    """Test analyze_observation in 'cached' mode."""

    def test_cached_mode_stores_and_replays(self, tmp_path: Path):
        scene = _make_test_scene("SEG-001", status="clear")
        image = _make_fake_png_bytes()
        cache_dir = tmp_path / "obs_cache"

        # Mock adapter as inner engine
        mock_inner = MagicMock(spec=VisionAdapter)
        mock_inner.model_id = "test-inner"
        analysis_mock = SceneAnalysis(
            scene_id=scene.scene_id,
            hazards=[],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.CLEAR,
                    confidence=0.80,
                    evidence="Inner clear",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-inner",
            prompt_version="v1",
        )
        mock_inner.analyze_scene.return_value = analysis_mock

        # First call: cache miss -> invokes inner adapter
        res1 = analyze_observation(
            image=image,
            zone_geometry=scene,
            mode="cached",
            inner_adapter=mock_inner,
            cache_dir=cache_dir,
        )
        assert mock_inner.analyze_scene.call_count == 1
        assert res1.guarded_verdicts["SEG-001"].status == RoadStatus.CLEAR

        # Second call with same inputs: cache hit -> inner adapter not called again
        res2 = analyze_observation(
            image=image,
            zone_geometry=scene,
            mode="cached",
            inner_adapter=mock_inner,
            cache_dir=cache_dir,
        )
        assert mock_inner.analyze_scene.call_count == 1
        assert res2.guarded_verdicts["SEG-001"].status == RoadStatus.CLEAR


# =============================================================================
# 3. Live Mode Tests (Blocker Reporting & Functionality)
# =============================================================================

class TestLiveMode:
    """Test analyze_observation in 'live' mode."""

    def test_live_mode_raises_not_implemented_error_when_provider_unregistered(self):
        """When an unregistered provider is requested, live mode must raise NotImplementedError."""
        scene = _make_test_scene()
        image = _make_fake_png_bytes()

        with pytest.raises(NotImplementedError) as exc_info:
            analyze_observation(image=image, zone_geometry=scene, mode="live", provider="unregistered_provider")

        error_msg = str(exc_info.value)
        assert "Live vision mode is blocked" in error_msg

    def test_live_mode_raises_value_error_when_api_key_missing(self, monkeypatch):
        """When gemini provider is registered but GEMINI_API_KEY is not set, raises ValueError."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        scene = _make_test_scene()
        image = _make_fake_png_bytes()

        with pytest.raises(ValueError) as exc_info:
            analyze_observation(image=image, zone_geometry=scene, mode="live")

        error_msg = str(exc_info.value)
        assert "GEMINI_API_KEY environment variable is not configured" in error_msg

    def test_live_mode_with_registered_adapter_succeeds(self):
        """If a live provider is registered, live mode executes it cleanly."""
        # Create a mock live adapter
        @register_adapter("test_live_prov")
        def _factory(model: str = "live-model", **kwargs):
            adapter = MagicMock(spec=VisionAdapter)
            adapter.model_id = "test-live-model"
            adapter.analyze_scene.return_value = SceneAnalysis(
                scene_id="S-0001",
                hazards=[],
                segment_verdicts={
                    "SEG-001": SegmentVerdict(
                        status=RoadStatus.CLEAR,
                        confidence=0.85,
                        evidence="Live clear",
                        visible=True,
                    )
                },
                image_quality_good=True,
                model_id="test-live-model",
                prompt_version="v1",
            )
            return adapter

        scene = _make_test_scene()
        image = _make_fake_png_bytes()

        result = analyze_observation(
            image=image,
            zone_geometry=scene,
            mode="live",
            provider="test_live_prov",
        )

        assert result.model_id == "test-live-model"
        assert result.guarded_verdicts["SEG-001"].status == RoadStatus.CLEAR

    def test_live_mode_with_explicit_adapter_kwarg(self):
        """Passing an explicit adapter instance in kwargs is supported."""
        custom_adapter = MagicMock(spec=VisionAdapter)
        custom_adapter.model_id = "custom-live"
        custom_adapter.analyze_scene.return_value = SceneAnalysis(
            scene_id="S-0001",
            hazards=[],
            segment_verdicts={
                "SEG-001": SegmentVerdict(status=RoadStatus.CLEAR, confidence=0.80, visible=True)
            },
            image_quality_good=True,
            model_id="custom-live",
            prompt_version="v1",
        )

        scene = _make_test_scene()
        image = _make_fake_png_bytes()

        result = analyze_observation(
            image=image,
            zone_geometry=scene,
            mode="live",
            adapter=custom_adapter,
        )

        assert result.model_id == "custom-live"
        assert custom_adapter.analyze_scene.call_count == 1


# =============================================================================
# 4. Input Variations & Validation
# =============================================================================

class TestInputVariations:
    """Test image and zone_geometry input handling."""

    def test_invalid_mode_raises_value_error(self):
        scene = _make_test_scene()
        image = _make_fake_png_bytes()

        with pytest.raises(ValueError, match="Invalid mode 'invalid'"):
            analyze_observation(image=image, zone_geometry=scene, mode="invalid")

    def test_image_from_file_path(self, tmp_path: Path):
        img_path = tmp_path / "test_image.png"
        img_path.write_bytes(_make_fake_png_bytes())

        scene = _make_test_scene()
        result = analyze_observation(image=img_path, zone_geometry=scene, mode="mock")

        assert result.model_id == "oracle-mock"

    def test_image_from_missing_file_path_raises_file_not_found(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.png"
        scene = _make_test_scene()

        with pytest.raises(FileNotFoundError, match="Image file not found"):
            analyze_observation(image=missing, zone_geometry=scene, mode="mock")

    def test_empty_image_bytes_raises_value_error(self):
        scene = _make_test_scene()
        with pytest.raises(ValueError, match="must not be empty"):
            analyze_observation(image=b"", zone_geometry=scene, mode="mock")

    def test_zone_geometry_as_segment_list(self):
        seg = _make_sample_segment("SEG-001")
        image = _make_fake_png_bytes()

        result = analyze_observation(image=image, zone_geometry=[seg], mode="mock")

        assert "SEG-001" in result.guarded_verdicts

    def test_zone_geometry_as_dict(self):
        seg = _make_sample_segment("SEG-001")
        scene_dict = _make_test_scene().model_dump()
        image = _make_fake_png_bytes()

        result = analyze_observation(image=image, zone_geometry=scene_dict, mode="mock")

        assert "SEG-001" in result.guarded_verdicts

    def test_invalid_zone_geometry_type_raises_type_error(self):
        image = _make_fake_png_bytes()
        with pytest.raises(TypeError, match="Unsupported zone_geometry type"):
            analyze_observation(image=image, zone_geometry=12345, mode="mock")


# =============================================================================
# 5. Result Interface (Dict & Attribute Access)
# =============================================================================

class TestObservationResultInterface:
    """Test ObservationResult attribute, dict, and property access."""

    def test_attribute_and_dict_access(self):
        scene = _make_test_scene()
        image = _make_fake_png_bytes()

        result = analyze_observation(image=image, zone_geometry=scene, mode="mock")

        # Attribute access
        assert result.model_id == "oracle-mock"
        assert result.prompt_version == "v1"
        assert result.latency >= 0
        assert result.latency_ms >= 0
        assert isinstance(result.hazards, list)
        assert isinstance(result.direct_verdicts, dict)
        assert isinstance(result.mapped_verdicts, dict)
        assert isinstance(result.guarded_verdicts, dict)

        # Dictionary access
        assert result["model_id"] == "oracle-mock"
        assert result["prompt_version"] == "v1"
        assert result["latency"] >= 0
        assert result["latency_ms"] >= 0
        assert result["hazards"] == result.hazards
        assert result["guarded_verdicts"] == result.guarded_verdicts
        assert result["final_verdicts"] == result.guarded_verdicts

        # get() method
        assert result.get("model_id") == "oracle-mock"
        assert result.get("missing_key", "default_val") == "default_val"

        # dict conversion / items iteration
        items = dict(result.items())
        assert "hazards" in items
        assert "guarded_verdicts" in items
        assert "latency" in items

    def test_metadata_dict_contents(self):
        scene = _make_test_scene()
        image = _make_fake_png_bytes()

        result = analyze_observation(image=image, zone_geometry=scene, mode="mock")

        meta = result.metadata
        assert meta["model_id"] == "oracle-mock"
        assert meta["prompt_version"] == "v1"
        assert "latency_ms" in meta
        assert meta["mode"] == "mock"

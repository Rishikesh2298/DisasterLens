"""
Unit tests for GeminiVisionAdapter (dl.vision.providers.gemini).

All tests use mocked Gemini SDK clients to verify adapter behavior without
network calls or real credentials.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dl.contracts.enums import Difficulty, HazardType, RoadStatus, Verdict
from dl.contracts.scene import Box, GroundTruth, RoadNode, RoadSegment, Scene
from dl.contracts.vision import SceneAnalysis
from dl.vision.base import VisionAdapter
from dl.vision.providers.gemini import GeminiVisionAdapter, _sanitize_error
from dl.vision.registry import get_adapter, list_registered_providers


def _make_sample_scene() -> Scene:
    return Scene(
        scene_id="S-0001",
        difficulty=Difficulty.EASY,
        split="dev",
        seed=0,
        image_width=512,
        image_height=512,
        nodes=[RoadNode(node_id="N1", x=0.0, y=0.0), RoadNode(node_id="N2", x=100.0, y=0.0)],
        segments=[
            RoadSegment(
                segment_id="SEG-001",
                from_node="N1",
                to_node="N2",
                length=100.0,
                centerline=[(0.0, 0.0), (100.0, 0.0)],
                polygon=[(0.0, -10.0), (100.0, -10.0), (100.0, 10.0), (0.0, 10.0)],
            )
        ],
        hazards=[],
        ground_truth=GroundTruth(
            hazards=[],
            segment_status={},
            damaged_building_count=0,
            water_regions=[],
            route_questions={},
            zone_comparisons={},
        ),
    )


def _make_mock_client(response_text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp
    return mock_client


# =============================================================================
# 1. Provider Registration & Interface Compliance
# =============================================================================

class TestGeminiProviderRegistration:
    def test_gemini_provider_is_registered(self):
        registered = list_registered_providers()
        assert "gemini" in registered

    def test_is_subclass_of_vision_adapter(self):
        assert issubclass(GeminiVisionAdapter, VisionAdapter)

    def test_get_adapter_resolves_gemini(self):
        mock_client = _make_mock_client("{}")
        adapter = get_adapter(provider="gemini", mode="live", client=mock_client)
        assert isinstance(adapter, GeminiVisionAdapter)


# =============================================================================
# 2. Model Configuration & Credential Safety
# =============================================================================

class TestModelAndCredentials:
    def test_model_configuration_default(self, monkeypatch):
        monkeypatch.delenv("VISION_MODEL", raising=False)
        mock_client = _make_mock_client("{}")
        adapter = GeminiVisionAdapter(client=mock_client)
        assert adapter.model_id == "gemini-1.5-pro"

    def test_model_configuration_env_override(self, monkeypatch):
        monkeypatch.setenv("VISION_MODEL", "gemini-3.8-flash")
        mock_client = _make_mock_client("{}")
        adapter = GeminiVisionAdapter(client=mock_client)
        assert adapter.model_id == "gemini-3.8-flash"

    def test_model_configuration_explicit_param(self):
        mock_client = _make_mock_client("{}")
        adapter = GeminiVisionAdapter(model="custom-gemini-test", client=mock_client)
        assert adapter.model_id == "custom-gemini-test"

    def test_missing_credentials_raises_clean_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        adapter = GeminiVisionAdapter()
        scene = _make_sample_scene()

        with pytest.raises(ValueError) as excinfo:
            adapter.analyze_scene(b"image_bytes", scene)

        err = str(excinfo.value)
        assert "GEMINI_API_KEY environment variable is not configured" in err
        assert "AIza" not in err

    def test_sanitize_error_masks_key(self):
        fake_key = "AIzaSyFakeSecretKey1234567890"
        err = f"Error calling endpoint https://api.com?key={fake_key}&foo=bar with secret {fake_key}"
        clean = _sanitize_error(err, secret=fake_key)
        assert fake_key not in clean
        assert "[REDACTED" in clean


# =============================================================================
# 3. Scene Analysis Submission & Parsing
# =============================================================================

class TestAnalyzeScene:
    def test_analyze_scene_valid_json_response(self, monkeypatch):
        monkeypatch.delenv("VISION_MODEL", raising=False)
        valid_json = """{
            "hazards": [
                {"type": "flood", "bbox": [10.0, 10.0, 50.0, 50.0], "confidence": 0.95}
            ],
            "segment_verdicts": {
                "SEG-001": {
                    "status": "blocked",
                    "confidence": 0.85,
                    "evidence": "Flooding across entire road.",
                    "visible": true
                }
            },
            "damaged_building_count": 1,
            "water_regions": [],
            "image_quality_good": true
        }"""
        mock_client = _make_mock_client(valid_json)
        adapter = GeminiVisionAdapter(client=mock_client)
        scene = _make_sample_scene()

        analysis = adapter.analyze_scene(b"test_image_png", scene)

        assert isinstance(analysis, SceneAnalysis)
        assert analysis.valid_json is True
        assert analysis.scene_id == "S-0001"
        assert analysis.model_id == "gemini-1.5-pro"
        assert len(analysis.hazards) == 1
        assert analysis.hazards[0].type == HazardType.FLOOD
        assert analysis.segment_verdicts["SEG-001"].status == RoadStatus.BLOCKED
        assert analysis.segment_verdicts["SEG-001"].confidence == 0.85

        # Check call arguments
        assert mock_client.models.generate_content.called
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-1.5-pro"
        contents = call_kwargs["contents"]
        assert len(contents) == 2  # image Part and prompt text

    def test_analyze_scene_image_variant_labelled(self):
        mock_client = _make_mock_client("{}")
        adapter = GeminiVisionAdapter(client=mock_client, image_variant="labelled")
        scene = _make_sample_scene()

        analysis = adapter.analyze_scene(b"test_image_png", scene)
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        prompt_text = call_kwargs["contents"][1]
        assert "labeled road segment" in prompt_text or "labelled" in prompt_text.lower()

    def test_malformed_response_handled_gracefully(self):
        # Model returns non-JSON conversational output
        mock_client = _make_mock_client("I cannot determine the road status from this picture.")
        adapter = GeminiVisionAdapter(client=mock_client)
        scene = _make_sample_scene()

        analysis = adapter.analyze_scene(b"test_image_png", scene)

        assert isinstance(analysis, SceneAnalysis)
        assert analysis.valid_json is False
        assert analysis.segment_verdicts == {}

    def test_api_exception_is_sanitized_and_raised(self):
        mock_client = MagicMock()
        fake_key = "SECRET_KEY_XYZ"
        mock_client.models.generate_content.side_effect = RuntimeError(f"Connection failed: key={fake_key}")

        adapter = GeminiVisionAdapter(client=mock_client, api_key=fake_key)
        scene = _make_sample_scene()

        with pytest.raises(RuntimeError) as excinfo:
            adapter.analyze_scene(b"test_image_png", scene)

        err = str(excinfo.value)
        assert fake_key not in err
        assert "[REDACTED" in err


# =============================================================================
# 4. Route Questions & Zone Comparison
# =============================================================================

class TestRouteQuestionsAndZoneComparison:
    def test_answer_route_questions_success(self):
        qa_json = '{"Q-001": "obstructed", "Q-002": "clear"}'
        mock_client = _make_mock_client(qa_json)
        adapter = GeminiVisionAdapter(client=mock_client)
        scene = _make_sample_scene()

        answers = adapter.answer_route_questions(
            image_bytes=b"png",
            questions={"Q-001": "Is N1 to N2 blocked?", "Q-002": "Is N2 to N3 blocked?"},
            scene=scene,
        )

        assert answers["Q-001"] == Verdict.OBSTRUCTED
        assert answers["Q-002"] == Verdict.CLEAR

    def test_compare_zones_success(self):
        zone_json = '{"zone_with_more": "zone_b"}'
        mock_client = _make_mock_client(zone_json)
        adapter = GeminiVisionAdapter(client=mock_client)
        scene = _make_sample_scene()

        res = adapter.compare_zones(
            image_bytes=b"png",
            zone_a=Box((0.0, 0.0, 100.0, 100.0)),
            zone_b=Box((100.0, 0.0, 200.0, 100.0)),
            scene=scene,
        )

        assert res == "zone_b"

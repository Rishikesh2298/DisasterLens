"""
Unit tests for deterministic MockVisionProvider.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dl.contracts.scene import GroundTruth, HazardType, RoadStatus, Scene, Zone
from dl.vision.mock import MockVisionProvider

DEMO_SCENE_PATH = Path(__file__).parent.parent / "scenarios" / "demo_city" / "scene.json"
DEMO_GT_PATH = Path(__file__).parent.parent / "scenarios" / "demo_city" / "ground_truth.json"


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 11, 27, 8, 0, 0, tzinfo=UTC)


@pytest.fixture
def mock_vision() -> MockVisionProvider:
    return MockVisionProvider()


class TestMockVisionProvider:
    """Tests 11–15: Mock vision provider determinism, timestamps, statuses, and near-misses."""

    def test_11_near_miss_does_not_create_road_blockage(
        self, mock_vision: MockVisionProvider, base_time: datetime
    ):
        """11. Near-miss observations do not create road blockage by proximity alone."""
        obs = mock_vision.create_observation(
            segment_id="SEG-005",
            source="synthetic_camera_2",
            zone=Zone.NE,
            captured_at=base_time,
            verdict=RoadStatus.CLEAR,
            hazard_type=HazardType.DEBRIS,
            near_miss=True,
        )

        assert obs.verdict == RoadStatus.CLEAR
        assert obs.near_miss is True
        assert obs.max_coverage < 0.30
        assert "no obstruction detected" in obs.evidence.lower()
        assert obs.is_mock is True

    def test_12_multiple_affected_segments_processed_correctly(
        self, mock_vision: MockVisionProvider, base_time: datetime
    ):
        """12. Multiple affected segments are processed correctly from scenario payloads."""
        raw_event_obs = {
            "source": "synthetic_camera_1",
            "capture_time": base_time.isoformat(),
            "zone": "NW",
            "affected_segments": ["SEG-001", "SEG-002", "SEG-003"],
            "hazard_type": "flood",
        }
        observations = mock_vision.from_scenario_event_observation(raw_event_obs)

        assert len(observations) == 3
        segment_ids = [o.segment_id for o in observations]
        assert segment_ids == ["SEG-001", "SEG-002", "SEG-003"]
        for o in observations:
            assert o.verdict == RoadStatus.BLOCKED
            assert o.source == "synthetic_camera_1"
            assert o.zone == Zone.NW
            assert o.hazard_type == HazardType.FLOOD

    def test_13_mock_provider_produces_deterministic_output(
        self, mock_vision: MockVisionProvider, base_time: datetime
    ):
        """13. Mock provider produces byte-for-byte identical output for identical inputs."""
        obs1 = mock_vision.create_observation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED, hazard_type=HazardType.FLOOD
        )
        obs2 = mock_vision.create_observation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED, hazard_type=HazardType.FLOOD
        )

        assert obs1.segment_id == obs2.segment_id
        assert obs1.verdict == obs2.verdict
        assert obs1.confidence == obs2.confidence
        assert obs1.evidence == obs2.evidence
        assert obs1.is_mock is True

    def test_14_mock_provider_preserves_capture_timestamps(
        self, mock_vision: MockVisionProvider, base_time: datetime
    ):
        """14. Mock provider preserves supplied capture timestamps."""
        obs = mock_vision.create_observation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.CLEAR
        )
        assert obs.captured_at == base_time

    def test_15_mock_provider_supports_all_required_statuses(
        self, mock_vision: MockVisionProvider, base_time: datetime
    ):
        """15. Mock provider supports CLEAR, BLOCKED, PARTIAL, and UNCERTAIN observations."""
        for status in [RoadStatus.CLEAR, RoadStatus.BLOCKED, RoadStatus.PARTIAL, RoadStatus.UNCERTAIN]:
            obs = mock_vision.create_observation(
                segment_id="SEG-010", source="cam1", zone=Zone.NE,
                captured_at=base_time, verdict=status
            )
            assert obs.verdict == status
            assert obs.is_mock is True

    def test_from_ground_truth_oracle(self, mock_vision: MockVisionProvider, base_time: datetime):
        """Validates oracle generation from demo city ground truth."""
        with open(DEMO_SCENE_PATH, "r", encoding="utf-8") as f:
            scene = Scene.model_validate_json(f.read())
        with open(DEMO_GT_PATH, "r", encoding="utf-8") as f:
            gt = GroundTruth.model_validate_json(f.read())

        observations = mock_vision.from_ground_truth(scene, gt, captured_at=base_time)
        assert len(observations) == 60

        blocked_obs = [o for o in observations if o.verdict == RoadStatus.BLOCKED]
        clear_obs = [o for o in observations if o.verdict == RoadStatus.CLEAR]

        assert len(blocked_obs) == 1
        assert blocked_obs[0].segment_id == "SEG-001"
        assert len(clear_obs) == 59

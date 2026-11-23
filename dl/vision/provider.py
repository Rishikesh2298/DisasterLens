"""
Vision provider abstraction and factory for DisasterLens.

Supports 'mock' (deterministic synthetic scene inference), 'cached' (pre-recorded),
and 'live' (vision LLM inference) operating modes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from dl.contracts.observation import SegmentObservation
from dl.contracts.scene import GroundTruth, Scene, Zone
from dl.vision.mock import MockVisionProvider


class VisionProviderError(Exception):
    """Raised when a vision provider operation fails or is unsupported."""


class VisionProvider(ABC):
    """Abstract base class for vision inference providers."""

    @property
    @abstractmethod
    def mode(self) -> str:
        """Operating mode name ('mock', 'cached', 'live')."""

    @abstractmethod
    def process_observation_payload(
        self,
        raw_obs: dict[str, Any],
        default_zone: Zone | None = None,
    ) -> list[SegmentObservation]:
        """Processes a raw observation payload into validated SegmentObservation objects."""


class MockProviderWrapper(VisionProvider):
    """Full implementation for deterministic mock vision."""

    def __init__(self) -> None:
        self._mock = MockVisionProvider()

    @property
    def mode(self) -> str:
        return "mock"

    def process_observation_payload(
        self,
        raw_obs: dict[str, Any],
        default_zone: Zone | None = None,
    ) -> list[SegmentObservation]:
        # Preserve provider metadata
        obs_list = self._mock.from_scenario_step(raw_obs, default_zone=default_zone)
        for obs in obs_list:
            obs.is_mock = True
            obs.model_id = "mock"
        return obs_list

    def from_ground_truth(
        self,
        scene: Scene,
        ground_truth: GroundTruth,
        captured_at: datetime,
        source: str = "oracle_camera",
    ) -> list[SegmentObservation]:
        return self._mock.from_ground_truth(
            scene=scene,
            ground_truth=ground_truth,
            captured_at=captured_at,
            source=source,
        )


class CachedVisionProvider(VisionProvider):
    """Stub for cached vision responses."""

    @property
    def mode(self) -> str:
        return "cached"

    def process_observation_payload(
        self,
        raw_obs: dict[str, Any],
        default_zone: Zone | None = None,
    ) -> list[SegmentObservation]:
        raise VisionProviderError(
            "Cached vision mode is not configured with an active cache store. "
            "Please switch VISION_MODE to 'mock' or configure the vision cache repository."
        )


class LiveVisionProvider(VisionProvider):
    """Stub for live model inference (e.g. Gemini 1.5 Flash)."""

    def __init__(self, model_name: str = "gemini-1.5-flash") -> None:
        self.model_name = model_name

    @property
    def mode(self) -> str:
        return "live"

    def process_observation_payload(
        self,
        raw_obs: dict[str, Any],
        default_zone: Zone | None = None,
    ) -> list[SegmentObservation]:
        raise VisionProviderError(
            f"Live vision mode with model '{self.model_name}' requires live API credentials "
            "and external network access. Please configure GEMINI_API_KEY or set VISION_MODE=mock."
        )


def get_vision_provider(mode: str | None = None, model: str = "gemini-1.5-flash") -> VisionProvider:
    """Factory function returning the configured vision provider."""
    normalized_mode = (mode or "mock").strip().lower()
    if normalized_mode == "mock":
        return MockProviderWrapper()
    elif normalized_mode == "cached":
        return CachedVisionProvider()
    elif normalized_mode == "live":
        return LiveVisionProvider(model_name=model)
    else:
        raise ValueError(
            f"Unknown VISION_MODE: '{mode}'. Supported modes are 'mock', 'cached', and 'live'."
        )

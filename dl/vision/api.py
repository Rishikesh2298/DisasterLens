"""
dl/vision/api.py
----------------
Backend-facing Vision AI engine API for DisasterLens.

Exposes the primary integration endpoint used by backend services
(such as Rajneesh's observation upload endpoint):

    analyze_observation(image, zone_geometry, mode, ...)

Capabilities:
1. Accepts an uploaded image (bytes or path), zone geometry (Scene or RoadSegment list),
   and execution mode ('mock', 'cached', 'live').
2. Executes the vision model adapter:
   - 'mock': Ground-truth oracle adapter (MockVisionAdapter).
   - 'cached': SHA-256 response cache wrapper (CachedVisionAdapter).
   - 'live': Real multimodal model adapter (raises descriptive NotImplementedError
             if provider adapter is unconfigured/empty).
3. Reuses existing geometric mapper (dl.vision.mapper) and safety guards (dl.vision.guards).
4. Returns detected hazards, direct model verdicts, mapped verdicts, and guarded
   final verdicts along with execution metadata (model ID, prompt version, latency).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Collection
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dl.contracts.enums import Difficulty, RoadStatus
from dl.contracts.scene import GroundTruth, RoadSegment, Scene
from dl.contracts.vision import PredictedHazard, SceneAnalysis, SegmentVerdict
from dl.vision.base import VisionAdapter
from dl.vision.cache import CachedVisionAdapter
from dl.vision.guards import apply_guards
from dl.vision.mapper import RoadMappingResult, map_hazards_to_roads
from dl.vision.registry import _try_lazy_load_provider, get_adapter, list_registered_providers

logger = logging.getLogger(__name__)

SUPPORTED_MODES = frozenset({"mock", "cached", "live"})


class ObservationResult(BaseModel):
    """
    Standardized result returned by analyze_observation.

    Supports both attribute access (result.hazards) and dictionary-style access
    (result["hazards"]) for seamless integration with downstream services.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    hazards: list[PredictedHazard] = Field(default_factory=list)
    direct_verdicts: dict[str, SegmentVerdict] = Field(default_factory=dict)
    mapped_verdicts: dict[str, RoadMappingResult] = Field(default_factory=dict)
    guarded_verdicts: dict[str, SegmentVerdict] = Field(default_factory=dict)
    model_id: str
    prompt_version: str
    latency_ms: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def latency(self) -> int:
        """Alias for latency_ms."""
        return self.latency_ms

    @property
    def final_verdicts(self) -> dict[str, SegmentVerdict]:
        """Alias for guarded_verdicts."""
        return self.guarded_verdicts

    def __getitem__(self, item: str) -> Any:
        if item in ("latency", "latency_ms"):
            return self.latency_ms
        if item in ("final_verdicts", "guarded_final_verdicts"):
            return self.guarded_verdicts
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default

    def keys(self):
        d = self.model_dump()
        d["latency"] = self.latency_ms
        d["final_verdicts"] = self.guarded_verdicts
        return d.keys()

    def items(self):
        d = self.model_dump()
        d["latency"] = self.latency_ms
        d["final_verdicts"] = self.guarded_verdicts
        return d.items()

    def values(self):
        d = self.model_dump()
        d["latency"] = self.latency_ms
        d["final_verdicts"] = self.guarded_verdicts
        return d.values()


def _resolve_image_bytes(image: bytes | str | Path | Any) -> bytes:
    """Extract raw image bytes from bytes, filepath, or file-like object."""
    if isinstance(image, bytes):
        if not image:
            raise ValueError("Image bytes must not be empty.")
        return image

    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")
        content = path.read_bytes()
        if not content:
            raise ValueError(f"Image file is empty: {path}")
        return content

    if hasattr(image, "read"):
        content = image.read()
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not content:
            raise ValueError("Image file-like object returned empty data.")
        return content

    raise TypeError(f"Unsupported image type '{type(image).__name__}'. Expected bytes, Path, or str.")


def _resolve_scene_and_segments(
    zone_geometry: Scene | Collection[RoadSegment] | dict[str, Any] | Any,
) -> tuple[Scene, list[RoadSegment]]:
    """
    Resolve zone geometry input into a contract-valid Scene and list of RoadSegments.
    """
    if isinstance(zone_geometry, Scene):
        return zone_geometry, list(zone_geometry.segments)

    if isinstance(zone_geometry, (list, tuple, set)):
        segments = [s for s in zone_geometry if isinstance(s, RoadSegment)]
        if not segments:
            raise ValueError("zone_geometry sequence contains no valid RoadSegment instances.")

        # Construct minimal contract-compliant Scene
        scene = Scene(
            scene_id="observation-scene",
            difficulty=Difficulty.EASY,
            split="dev",
            seed=0,
            image_width=512,
            image_height=512,
            nodes=[],
            segments=segments,
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
        return scene, segments

    if isinstance(zone_geometry, dict):
        if "segments" in zone_geometry and "nodes" in zone_geometry and "ground_truth" in zone_geometry:
            scene = Scene.model_validate(zone_geometry)
            return scene, list(scene.segments)

        if "segments" in zone_geometry:
            segments = [
                s if isinstance(s, RoadSegment) else RoadSegment.model_validate(s)
                for s in zone_geometry["segments"]
            ]
            scene = Scene(
                scene_id=zone_geometry.get("scene_id", "observation-scene"),
                difficulty=zone_geometry.get("difficulty", Difficulty.EASY),
                split=zone_geometry.get("split", "dev"),
                seed=zone_geometry.get("seed", 0),
                image_width=zone_geometry.get("image_width", 512),
                image_height=zone_geometry.get("image_height", 512),
                nodes=[],
                segments=segments,
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
            return scene, segments

    raise TypeError(
        f"Unsupported zone_geometry type '{type(zone_geometry).__name__}'. "
        "Expected Scene, Collection[RoadSegment], or valid dict."
    )


def _resolve_adapter(
    mode: str,
    **kwargs: Any,
) -> VisionAdapter:
    """
    Instantiate the appropriate VisionAdapter according to the requested mode.

    Raises:
        NotImplementedError: If live mode is requested but no live provider is available.
    """
    if mode == "mock":
        adapter = kwargs.pop("adapter", None)
        if adapter is not None:
            return adapter
        return get_adapter(mode="mock", **kwargs)

    if mode == "cached":
        cache_dir = kwargs.pop("cache_dir", None)
        inner = kwargs.pop("inner_adapter", None)
        if inner is None:
            provider = kwargs.pop("provider", None) or os.getenv("VISION_PROVIDER")
            if provider:
                _try_lazy_load_provider(provider)
            if provider and provider in list_registered_providers() and provider != "mock":
                inner = get_adapter(mode="live", provider=provider, **kwargs)
            else:
                inner = get_adapter(mode="mock", **kwargs)

        return CachedVisionAdapter(inner_adapter=inner, cache_dir=cache_dir, **kwargs)

    if mode == "live":
        # Check if an adapter was explicitly provided (e.g. for testing)
        adapter = kwargs.pop("adapter", None)
        if adapter is not None:
            return adapter

        provider = kwargs.get("provider", os.getenv("VISION_PROVIDER", "gemini"))
        _try_lazy_load_provider(provider)  # load the provider module before checking the registry
        registered = list_registered_providers()

        # Check if the provider is available in registry
        if provider not in registered:
            raise NotImplementedError(
                f"Live vision mode is blocked: provider adapter '{provider}' is not available. "
                f"Registered providers: {registered}. "
                "dl/vision/providers/gemini.py is empty and live API integration has not yet been implemented."
            )

        return get_adapter(mode="live", **kwargs)

    raise ValueError(f"Invalid mode '{mode}'. Allowed modes: {sorted(SUPPORTED_MODES)}")


def analyze_observation(
    image: bytes | str | Path | Any,
    zone_geometry: Scene | Collection[RoadSegment] | dict[str, Any] | Any,
    mode: str = "mock",
    *,
    prompt_version: str = "v1",
    **kwargs: Any,
) -> ObservationResult:
    """
    Analyze an uploaded camera observation image against zone road geometry.

    Args:
        image: Binary image bytes, filepath (str/Path), or file-like object.
        zone_geometry: Scene, sequence of RoadSegment, or scene dictionary.
        mode: Execution mode ('mock', 'cached', or 'live'). Default: 'mock'.
        prompt_version: Prompt version string. Default: 'v1'.
        **kwargs: Optional provider, model, adapter, or cache_dir configurations.

    Returns:
        ObservationResult containing:
        - hazards: Detected PredictedHazard instances.
        - direct_verdicts: Raw model verdicts from vision adapter.
        - mapped_verdicts: Geometric cross-section mapping results.
        - guarded_verdicts: Final safety-guarded verdicts for relevant segments.
        - model_id: Identifier of model used.
        - prompt_version: Prompt version tag.
        - latency_ms: Wall-clock execution time in milliseconds.
        - metadata: Dictionary containing model and latency metadata.

    Raises:
        ValueError: If mode is unsupported or inputs are invalid.
        FileNotFoundError: If an image path does not exist.
        NotImplementedError: If live mode is requested but no provider is implemented.
    """
    mode_normalized = str(mode).strip().lower()
    if mode_normalized not in SUPPORTED_MODES:
        raise ValueError(
            f"Invalid mode '{mode}'. Allowed modes are: {sorted(SUPPORTED_MODES)}"
        )

    image_bytes = _resolve_image_bytes(image)
    scene, segments = _resolve_scene_and_segments(zone_geometry)

    # 1. Resolve and execute vision adapter
    adapter = _resolve_adapter(mode_normalized, **kwargs)

    t0 = time.perf_counter()
    direct_analysis: SceneAnalysis = adapter.analyze_scene(
        image_bytes=image_bytes,
        scene=scene,
        prompt_version=prompt_version,
    )
    latency_ms = max(0, int((time.perf_counter() - t0) * 1000))

    # 2. Geometric hazard-to-road mapping (dl.vision.mapper)
    mapped_results: dict[str, RoadMappingResult] = {}
    valid_mapping_segments = [
        seg for seg in segments
        if seg.polygon and len(seg.polygon) >= 3 and seg.centerline and len(seg.centerline) >= 2
    ]
    if valid_mapping_segments:
        mapped_results = map_hazards_to_roads(
            segments=valid_mapping_segments,
            hazards=direct_analysis.hazards,
        )

    # 3. Apply safety guards (dl.vision.guards)
    guarded_analysis = apply_guards(
        analysis=direct_analysis,
        mapped_verdicts=mapped_results,
    )

    # Filter guarded verdicts to relevant segments in zone_geometry
    relevant_ids = {seg.segment_id for seg in segments}
    guarded_verdicts = {
        seg_id: v for seg_id, v in guarded_analysis.segment_verdicts.items()
        if seg_id in relevant_ids
    }
    # If any relevant segment was not returned by model, provide UNCERTAIN fallback
    for seg_id in relevant_ids:
        if seg_id not in guarded_verdicts:
            guarded_verdicts[seg_id] = SegmentVerdict(
                status=RoadStatus.UNCERTAIN,
                confidence=0.0,
                evidence="Segment not included in model analysis output.",
                visible=None,
            )

    model_id = direct_analysis.model_id
    metadata = {
        "model_id": model_id,
        "prompt_version": prompt_version,
        "latency_ms": latency_ms,
        "mode": mode_normalized,
    }

    return ObservationResult(
        hazards=direct_analysis.hazards,
        direct_verdicts=direct_analysis.segment_verdicts,
        mapped_verdicts=mapped_results,
        guarded_verdicts=guarded_verdicts,
        model_id=model_id,
        prompt_version=prompt_version,
        latency_ms=latency_ms,
        metadata=metadata,
    )

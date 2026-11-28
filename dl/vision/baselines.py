"""
dl/vision/baselines.py
----------------------
Non-AI, deterministic baselines for DisasterLens evaluation.

Three baselines are provided:

  1. AlwaysClearBaseline      – predicts every road segment as CLEAR.
  2. ProximityBaseline        – predicts BLOCKED when any hazard centroid is
                               within a configurable pixel-distance threshold N
                               of a road segment's centreline; CLEAR otherwise.
  3. NoisyOracleBaseline      – takes the ground-truth oracle result and
                               applies configurable miss, false-positive and
                               near-miss confusion rates to simulate imperfect models.

IMPORTANT SAFETY RULES (apply to all three baselines):
  - None of these baselines make external API calls.
  - None of these baselines are real AI models.
  - model_id is set to a clearly labelled string (e.g. 'baseline-always-clear')
    so evaluation metrics can never confuse them with real AI outputs.
  - Shared contracts (dl/contracts/*) are never modified.
  - `scene.ground_truth` is read ONLY inside NoisyOracleBaseline, which is
    documented as a mock.  AlwaysClearBaseline and ProximityBaseline must
    never read ground truth (they simulate real models that have no access to it).

CONTRACT LIMITATIONS (documented, not worked around):
  - `SegmentVerdict.confidence` has an upper bound of 0.85 (enforced by the
    shared schema).  All baselines use 0.85 as their maximum confidence.
  - `SceneAnalysis` has no `is_mock` / `is_baseline` boolean field.  Baselines
    are identified exclusively via `model_id`.
  - `SegmentVerdict` has no `reason` field beyond the free-text `evidence` str.
"""

from __future__ import annotations

import math
import random
from typing import Any

from dl.contracts.enums import HazardType, RoadStatus, Verdict
from dl.contracts.scene import Box, Scene
from dl.contracts.vision import PredictedHazard, SceneAnalysis, SegmentVerdict
from dl.vision.base import VisionAdapter, ZoneComparisonResult

# ---------------------------------------------------------------------------
# Shared helper: build a minimal SceneAnalysis frame
# ---------------------------------------------------------------------------

def _base_analysis(
    scene: Scene,
    model_id: str,
    prompt_version: str,
    segment_verdicts: dict[str, SegmentVerdict],
    hazards: list[PredictedHazard] | None = None,
) -> SceneAnalysis:
    """
    Assemble a SceneAnalysis from pre-computed verdicts.

    Baselines never predict hazard bounding boxes (no image access or ML
    inference), so `hazards` defaults to an empty list.
    """
    return SceneAnalysis(
        scene_id=scene.scene_id,
        hazards=hazards or [],
        segment_verdicts=segment_verdicts,
        damaged_building_count=None,
        water_regions=[],
        image_quality_good=None,
        model_id=model_id,
        prompt_version=prompt_version,
        valid_json=True,
        latency_ms=0,
    )


# ---------------------------------------------------------------------------
# 1. AlwaysClearBaseline
# ---------------------------------------------------------------------------

class AlwaysClearBaseline(VisionAdapter):
    """
    Lower-bound baseline: every road segment is always predicted as CLEAR.

    Purpose
    -------
    Establishes a false-clear rate ceiling.  Any real model must beat this
    baseline on blocked / partial segment recall to be considered useful.

    Data access
    -----------
    Uses `scene.segments` only for segment IDs — never reads `scene.ground_truth`.
    Does not use image_bytes at all.

    Contract limitations
    --------------------
    `SegmentVerdict.confidence` is capped at 0.85 by the shared schema.
    """

    MODEL_ID = "baseline-always-clear"

    def __init__(self, **kwargs: Any) -> None:
        self.model_id = self.MODEL_ID

    def analyze_scene(
        self,
        image_bytes: bytes,
        scene: Scene,
        prompt_version: str = "v1",
    ) -> SceneAnalysis:
        """
        Return CLEAR for every road segment, regardless of image content.

        Args:
            image_bytes: Ignored — this baseline does not inspect the image.
            scene: Scene providing the list of road segment IDs.
            prompt_version: Forwarded unchanged to SceneAnalysis metadata.

        Returns:
            SceneAnalysis with CLEAR verdict for all segments in `scene.segments`.
        """
        verdicts: dict[str, SegmentVerdict] = {
            seg.segment_id: SegmentVerdict(
                status=RoadStatus.CLEAR,
                confidence=0.85,
                evidence="AlwaysClear baseline: unconditionally predicts CLEAR.",
                visible=None,
            )
            for seg in scene.segments
        }
        return _base_analysis(
            scene=scene,
            model_id=self.MODEL_ID,
            prompt_version=prompt_version,
            segment_verdicts=verdicts,
        )

    def answer_route_questions(
        self,
        image_bytes: bytes,
        questions: dict[str, str],
        scene: Scene,
        prompt_version: str = "v1",
    ) -> dict[str, Verdict]:
        """Always returns CLEAR for every route question."""
        return {q_id: Verdict.CLEAR for q_id in questions}

    def compare_zones(
        self,
        image_bytes: bytes,
        zone_a: Box,
        zone_b: Box,
        scene: Scene,
        comparison_id: str = "",
        prompt_version: str = "v1",
    ) -> ZoneComparisonResult:
        """Returns 'equal' — baseline has no information to prefer either zone."""
        return "equal"


# ---------------------------------------------------------------------------
# 2. ProximityBaseline
# ---------------------------------------------------------------------------

# Default distance threshold (pixels).  Adjust per dataset resolution.
DEFAULT_PROXIMITY_THRESHOLD_PX: float = 50.0


def _centroid_of_box(bbox: Box) -> tuple[float, float]:
    """Return the (x, y) centroid of a bounding box."""
    x1, y1, x2, y2 = bbox.root
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _min_distance_to_centerline(
    point: tuple[float, float],
    centerline: list[tuple[float, float]],
) -> float:
    """
    Return the minimum Euclidean distance from `point` to any segment of
    the polyline defined by `centerline`.

    For each consecutive pair of centerline vertices (A, B), we project
    `point` onto the line AB and clamp to [A, B], then measure the distance
    to the nearest point on that segment.

    Args:
        point: (px, py) pixel coordinate.
        centerline: List of (x, y) vertices forming the road polyline.

    Returns:
        Minimum distance in pixels.
    """
    px, py = point
    min_dist = math.inf

    for i in range(len(centerline) - 1):
        ax, ay = centerline[i]
        bx, by = centerline[i + 1]

        # Vector AB and AP
        abx, aby = bx - ax, by - ay
        apx, apy = px - ax, py - ay

        ab_sq = abx * abx + aby * aby
        if ab_sq < 1e-12:
            # Degenerate segment (zero length) — just measure to point A
            dist = math.hypot(apx, apy)
        else:
            # Scalar projection of P onto AB, clamped to [0, 1]
            t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_sq))
            # Nearest point on AB to P
            nearest_x = ax + t * abx
            nearest_y = ay + t * aby
            dist = math.hypot(px - nearest_x, py - nearest_y)

        min_dist = min(min_dist, dist)

    return min_dist


class ProximityBaseline(VisionAdapter):
    """
    Proximity-based heuristic baseline.

    Decision rule
    -------------
    For each road segment, compute the minimum distance from every hazard
    centroid (derived from its bounding box) to the segment's centreline.

    - If any non-building hazard is within `threshold_px` pixels → BLOCKED.
    - Otherwise → CLEAR.

    There is no PARTIAL verdict in this baseline; the binary decision rule
    is intentionally simple to show how proximity alone creates false positives
    for hazards that are *near* but not *on* the road.

    Configurable threshold
    ----------------------
    `threshold_px` (default: 50 pixels).  Increasing the threshold makes the
    baseline more aggressive (more false positives for nearby hazards).
    Decreasing it makes it more conservative.

    Data access
    -----------
    Uses `scene.segments` for geometry and `scene.hazards` for hazard bboxes.
    **Never reads `scene.ground_truth`.**  Does not use image_bytes.

    Contract limitations
    --------------------
    `scene.hazards` holds ground-layout geometry (not AI predictions), so this
    baseline effectively uses the known hazard *positions* without knowing
    road *status*.  This is intentional: it mimics a simple object-detection
    system that knows where hazards are but not whether they block roads.
    """

    MODEL_ID = "baseline-proximity"

    # Hazard types that the proximity rule considers (excludes DAMAGED_BUILDING,
    # matching mapper.py's convention that buildings alone do not block roads).
    _BLOCKING_HAZARD_TYPES: frozenset[HazardType] = frozenset({
        HazardType.FLOOD,
        HazardType.DEBRIS,
        HazardType.FALLEN_TREE,
        HazardType.ROAD_DAMAGE,
    })

    def __init__(
        self,
        threshold_px: float = DEFAULT_PROXIMITY_THRESHOLD_PX,
        **kwargs: Any,
    ) -> None:
        """
        Args:
            threshold_px: Pixel distance threshold.  Any hazard centroid within
                          this distance of a road centreline causes BLOCKED.
                          Must be a positive number.
        """
        if threshold_px <= 0:
            raise ValueError(
                f"threshold_px must be positive, got {threshold_px!r}."
            )
        self.threshold_px = threshold_px
        self.model_id = self.MODEL_ID

    def analyze_scene(
        self,
        image_bytes: bytes,
        scene: Scene,
        prompt_version: str = "v1",
    ) -> SceneAnalysis:
        """
        Predict road status based on hazard-centroid proximity.

        Args:
            image_bytes: Ignored.
            scene: Scene providing segment geometry and hazard bboxes.
            prompt_version: Forwarded to SceneAnalysis metadata.

        Returns:
            SceneAnalysis with BLOCKED/CLEAR verdicts based on proximity.
        """
        # Collect centroids of blocking hazards from scene layout (not ground truth)
        hazard_centroids: list[tuple[float, float]] = [
            _centroid_of_box(h.bbox)
            for h in scene.hazards
            if h.type in self._BLOCKING_HAZARD_TYPES
        ]

        verdicts: dict[str, SegmentVerdict] = {}

        for seg in scene.segments:
            if not seg.centerline or len(seg.centerline) < 2:
                # Degenerate segment — cannot evaluate proximity
                verdicts[seg.segment_id] = SegmentVerdict(
                    status=RoadStatus.UNCERTAIN,
                    confidence=0.0,
                    evidence="ProximityBaseline: segment has no valid centreline.",
                    visible=None,
                )
                continue

            # Find the minimum distance from any blocking hazard to this centreline
            min_dist = math.inf
            for centroid in hazard_centroids:
                d = _min_distance_to_centerline(centroid, seg.centerline)
                min_dist = min(min_dist, d)

            if min_dist <= self.threshold_px:
                verdicts[seg.segment_id] = SegmentVerdict(
                    status=RoadStatus.BLOCKED,
                    confidence=0.85,
                    evidence=(
                        f"ProximityBaseline: hazard centroid within {min_dist:.1f}px "
                        f"(threshold={self.threshold_px}px)."
                    ),
                    visible=None,
                )
            else:
                verdicts[seg.segment_id] = SegmentVerdict(
                    status=RoadStatus.CLEAR,
                    confidence=0.85,
                    evidence=(
                        f"ProximityBaseline: nearest hazard centroid is {min_dist:.1f}px "
                        f"(threshold={self.threshold_px}px)."
                    ),
                    visible=None,
                )

        return _base_analysis(
            scene=scene,
            model_id=self.MODEL_ID,
            prompt_version=prompt_version,
            segment_verdicts=verdicts,
        )

    def answer_route_questions(
        self,
        image_bytes: bytes,
        questions: dict[str, str],
        scene: Scene,
        prompt_version: str = "v1",
    ) -> dict[str, Verdict]:
        """Returns CLEAR for all questions — route evaluation is out of scope."""
        return {q_id: Verdict.CLEAR for q_id in questions}

    def compare_zones(
        self,
        image_bytes: bytes,
        zone_a: Box,
        zone_b: Box,
        scene: Scene,
        comparison_id: str = "",
        prompt_version: str = "v1",
    ) -> ZoneComparisonResult:
        """Returns 'equal' — zone comparison is out of scope for this baseline."""
        return "equal"


# ---------------------------------------------------------------------------
# 3. NoisyOracleBaseline
# ---------------------------------------------------------------------------

# Valid RoadStatus values present in ground truth
_GT_STATUSES: dict[str, RoadStatus] = {
    "blocked": RoadStatus.BLOCKED,
    "partial": RoadStatus.PARTIAL,
    "clear": RoadStatus.CLEAR,
}


class NoisyOracleBaseline(VisionAdapter):
    """
    Ground-truth oracle with configurable confusion noise.

    THIS IS A MOCK BASELINE.  It is not a real AI model.
    It reads `scene.ground_truth` directly — real providers must never do this.
    It is intended purely for evaluation sanity-checking and ablation studies.

    Noise model
    -----------
    Three independent noise rates control how the oracle is degraded:

    ``miss_rate``  (default 0.0)
        Probability that a BLOCKED or PARTIAL segment is predicted as CLEAR
        (simulates failing to detect an obstruction).

    ``false_positive_rate``  (default 0.0)
        Probability that a CLEAR segment is predicted as BLOCKED
        (simulates phantom obstruction hallucinations).

    ``near_miss_rate``  (default 0.0)
        Probability that a BLOCKED segment is predicted as PARTIAL instead
        (simulates underestimating severity).

    Noise is applied independently per segment using `random.Random` seeded
    with the provided ``seed``.  Using the same seed always produces the same
    output for the same scene, making experiments reproducible.

    Ordering of noise application (BLOCKED segments):
        1. Apply `miss_rate` first  → may flip BLOCKED to CLEAR.
        2. If not missed, apply `near_miss_rate` → may flip BLOCKED to PARTIAL.

    Contract limitations
    --------------------
    `SegmentVerdict.confidence` is capped at 0.85.
    There is no `is_mock` field in SceneAnalysis; identification is via model_id.

    WARNING
    -------
    Never use this baseline in production evaluation as a substitute for a
    real AI model.  Evaluation results obtained with this baseline measure
    noise tolerance, NOT AI model quality.
    """

    MODEL_ID = "baseline-noisy-oracle"

    def __init__(
        self,
        miss_rate: float = 0.0,
        false_positive_rate: float = 0.0,
        near_miss_rate: float = 0.0,
        seed: int | None = 42,
        **kwargs: Any,
    ) -> None:
        """
        Args:
            miss_rate: Probability [0, 1] that a blocked/partial segment is
                       predicted as CLEAR.
            false_positive_rate: Probability [0, 1] that a clear segment is
                                 predicted as BLOCKED.
            near_miss_rate: Probability [0, 1] that a blocked segment is
                            predicted as PARTIAL (applied after miss_rate).
            seed: Random seed for reproducibility.  Pass None for truly random
                  noise (not reproducible across runs).
        """
        for name, val in [
            ("miss_rate", miss_rate),
            ("false_positive_rate", false_positive_rate),
            ("near_miss_rate", near_miss_rate),
        ]:
            if not (0.0 <= val <= 1.0):
                raise ValueError(
                    f"{name} must be in [0, 1], got {val!r}."
                )

        self.miss_rate = miss_rate
        self.false_positive_rate = false_positive_rate
        self.near_miss_rate = near_miss_rate
        self.seed = seed
        self.model_id = self.MODEL_ID

    def _apply_noise(
        self,
        true_status: RoadStatus,
        rng: random.Random,
    ) -> tuple[RoadStatus, str]:
        """
        Apply noise to a single ground-truth road status.

        Returns:
            (noisy_status, evidence_string)
        """
        if true_status in (RoadStatus.BLOCKED, RoadStatus.PARTIAL):
            if rng.random() < self.miss_rate:
                return RoadStatus.CLEAR, (
                    f"NoisyOracle: ground truth={true_status.value}, "
                    f"flipped to CLEAR by miss_rate={self.miss_rate}."
                )
            if true_status == RoadStatus.BLOCKED and rng.random() < self.near_miss_rate:
                return RoadStatus.PARTIAL, (
                    f"NoisyOracle: ground truth=blocked, "
                    f"downgraded to PARTIAL by near_miss_rate={self.near_miss_rate}."
                )
            return true_status, (
                f"NoisyOracle: ground truth={true_status.value}, retained."
            )

        if true_status == RoadStatus.CLEAR:
            if rng.random() < self.false_positive_rate:
                return RoadStatus.BLOCKED, (
                    f"NoisyOracle: ground truth=clear, "
                    f"flipped to BLOCKED by false_positive_rate={self.false_positive_rate}."
                )
            return RoadStatus.CLEAR, (
                "NoisyOracle: ground truth=clear, retained."
            )

        # Statuses not in ground truth (UNCERTAIN, STALE, UNKNOWN) pass through
        return true_status, f"NoisyOracle: ground truth={true_status.value}, no noise applied."

    def analyze_scene(
        self,
        image_bytes: bytes,
        scene: Scene,
        prompt_version: str = "v1",
    ) -> SceneAnalysis:
        """
        Return oracle ground truth with noise applied.

        THIS BASELINE READS scene.ground_truth.
        It must never be used in a live evaluation pipeline that expects real
        AI model outputs.

        Args:
            image_bytes: Ignored.
            scene: Complete Scene — ground_truth is read.
            prompt_version: Forwarded to SceneAnalysis metadata.

        Returns:
            SceneAnalysis with ground-truth verdicts degraded by configured noise.
        """
        gt = scene.ground_truth

        # Seed a fresh RNG per call to ensure reproducibility when seed is fixed.
        rng = random.Random(self.seed)

        verdicts: dict[str, SegmentVerdict] = {}

        for seg_id, status_val in gt.segment_status.items():
            true_status = _GT_STATUSES.get(status_val, RoadStatus.UNKNOWN)
            noisy_status, evidence = self._apply_noise(true_status, rng)
            verdicts[seg_id] = SegmentVerdict(
                status=noisy_status,
                confidence=0.85,
                evidence=evidence,
                visible=True,
            )

        # Segments listed in scene.segments but absent from segment_status
        # are assigned UNCERTAIN (ground truth is incomplete for them).
        gt_seg_ids = set(gt.segment_status.keys())
        for seg in scene.segments:
            if seg.segment_id not in gt_seg_ids:
                verdicts[seg.segment_id] = SegmentVerdict(
                    status=RoadStatus.UNCERTAIN,
                    confidence=0.0,
                    evidence="NoisyOracle: segment not present in ground-truth segment_status.",
                    visible=None,
                )

        return _base_analysis(
            scene=scene,
            model_id=self.MODEL_ID,
            prompt_version=prompt_version,
            segment_verdicts=verdicts,
        )

    def answer_route_questions(
        self,
        image_bytes: bytes,
        questions: dict[str, str],
        scene: Scene,
        prompt_version: str = "v1",
    ) -> dict[str, Verdict]:
        """
        Return ground-truth answers with no noise applied.
        Route-question noise is not part of the Day 3 roadmap.
        """
        gt = scene.ground_truth
        results: dict[str, Verdict] = {}
        for q_id in questions:
            raw = gt.route_questions.get(q_id, "clear")
            results[q_id] = Verdict.OBSTRUCTED if raw == "obstructed" else Verdict.CLEAR
        return results

    def compare_zones(
        self,
        image_bytes: bytes,
        zone_a: Box,
        zone_b: Box,
        scene: Scene,
        comparison_id: str = "",
        prompt_version: str = "v1",
    ) -> ZoneComparisonResult:
        """Returns 'equal' — zone-comparison noise is not part of the roadmap."""
        return "equal"

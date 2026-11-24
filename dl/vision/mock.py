from typing import Any

from dl.contracts.enums import RoadStatus, Verdict
from dl.contracts.scene import Box, Scene
from dl.contracts.vision import PredictedHazard, SceneAnalysis, SegmentVerdict
from dl.vision.base import VisionAdapter, ZoneComparisonResult
from dl.vision.registry import register_adapter

# Recognized synonyms for zone comparison ground truth
ZONE_A_SYNONYMS = frozenset({"zone_a", "zone a", "a"})
ZONE_B_SYNONYMS = frozenset({"zone_b", "zone b", "b"})
EQUAL_SYNONYMS = frozenset({"equal", "tie", "same", "neither"})


@register_adapter("mock")
class MockVisionAdapter(VisionAdapter):
    """
    Ground-truth Oracle Mock Adapter for DisasterLens.

    Reads exact ground truth from `scene.ground_truth` and formats it into the
    validated `SceneAnalysis` contract. Used by backend and evaluation modules
    before real AI models are connected, or when API quotas are exhausted.

    IMPORTANT SAFETY & EVALUATION RULES:
    1. This mock never makes external API calls.
    2. Because the current `SceneAnalysis` shared contract does NOT define an `is_mock`
       field (and enforces `extra="forbid"`), mock results are ALWAYS identified
       by setting `model_id="oracle-mock"`.
    3. `SegmentVerdict.confidence` is capped at 0.85 to respect the existing contract limit.
    4. Unrecognized zone comparison ground-truth answers raise ValueError instead of
       silently defaulting.
    """

    def __init__(self, model: str = "oracle-mock", **kwargs: Any) -> None:
        # Enforce oracle-mock identification regardless of input parameters
        self.model_id = "oracle-mock"

    def analyze_scene(
        self,
        image_bytes: bytes,
        scene: Scene,
        prompt_version: str = "v1",
    ) -> SceneAnalysis:
        """
        Produce a perfect SceneAnalysis object directly from ground truth.

        Args:
            image_bytes: Raw binary image content (ignored by oracle mock).
            scene: Complete Scene containing ground truth.
            prompt_version: Version tag of prompt.

        Returns:
            SceneAnalysis: Contract object with exact ground-truth predictions.
        """
        gt = scene.ground_truth

        # 1. Map hazards to PredictedHazard
        predicted_hazards: list[PredictedHazard] = [
            PredictedHazard(
                type=hazard.type,
                bbox=hazard.bbox,
                confidence=1.0,  # PredictedHazard allows le=1.0
            )
            for hazard in gt.hazards
        ]

        # 2. Map road segment statuses to SegmentVerdict
        # Note: SegmentVerdict enforces confidence le=0.85
        segment_verdicts: dict[str, SegmentVerdict] = {}
        for segment_id, status_val in gt.segment_status.items():
            road_status = RoadStatus(status_val)
            segment_verdicts[segment_id] = SegmentVerdict(
                status=road_status,
                confidence=0.85,  # Maximum confidence allowed by Rishikesh's schema
                evidence=f"Oracle ground truth: {road_status.value}",
                visible=True,
            )

        # 3. Assemble and return validated SceneAnalysis
        # Always use model_id="oracle-mock" to identify mock results
        return SceneAnalysis(
            scene_id=scene.scene_id,
            hazards=predicted_hazards,
            segment_verdicts=segment_verdicts,
            damaged_building_count=gt.damaged_building_count,
            water_regions=list(gt.water_regions),
            image_quality_good=True,
            model_id="oracle-mock",
            prompt_version=prompt_version,
            valid_json=True,
            latency_ms=0,
        )

    def answer_route_questions(
        self,
        image_bytes: bytes,
        questions: dict[str, str],
        scene: Scene,
        prompt_version: str = "v1",
    ) -> dict[str, Verdict]:
        """
        Return ground-truth answers for route obstruction questions.

        Args:
            image_bytes: Raw binary image content (ignored).
            questions: Dictionary mapping question IDs to question prompts.
            scene: Complete Scene containing ground-truth route questions.
            prompt_version: Prompt version tag.

        Returns:
            dict[str, Verdict]: Map of question ID to Verdict.CLEAR or Verdict.OBSTRUCTED.

        Raises:
            KeyError: If a requested question ID is not present in ground truth.
        """
        gt = scene.ground_truth
        results: dict[str, Verdict] = {}

        for q_id in questions.keys():
            if q_id not in gt.route_questions:
                available = list(gt.route_questions.keys())
                raise KeyError(
                    f"Route question '{q_id}' not found in ground truth for scene '{scene.scene_id}'. "
                    f"Available questions: {available}"
                )
            answer_str = gt.route_questions[q_id]
            results[q_id] = Verdict(answer_str)

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
        """
        Return ground-truth zone comparison verdict ('zone_a', 'zone_b', or 'equal').

        Args:
            image_bytes: Raw binary image content (ignored).
            zone_a: Bounding box for Zone A.
            zone_b: Bounding box for Zone B.
            scene: Complete Scene containing ground truth.
            comparison_id: Identifier of the zone comparison question.
            prompt_version: Prompt version tag.

        Returns:
            ZoneComparisonResult: 'zone_a', 'zone_b', or 'equal'.

        Raises:
            KeyError: If comparison_id is not found in ground truth.
            ValueError: If comparison_id is omitted and cannot be disambiguated,
                        or if ground-truth answer is unrecognized.
        """
        gt = scene.ground_truth

        if comparison_id:
            if comparison_id not in gt.zone_comparisons:
                available = list(gt.zone_comparisons.keys())
                raise KeyError(
                    f"Zone comparison '{comparison_id}' not found in ground truth for scene '{scene.scene_id}'. "
                    f"Available comparisons: {available}"
                )
            raw_answer = gt.zone_comparisons[comparison_id].strip().lower()
        else:
            if len(gt.zone_comparisons) == 1:
                raw_answer = next(iter(gt.zone_comparisons.values())).strip().lower()
            elif not gt.zone_comparisons:
                raise KeyError(
                    f"No zone comparisons available in ground truth for scene '{scene.scene_id}'."
                )
            else:
                available = list(gt.zone_comparisons.keys())
                raise ValueError(
                    f"Multiple zone comparisons exist for scene '{scene.scene_id}'. "
                    f"Please provide comparison_id from: {available}"
                )

        # Normalize and validate raw answer
        if raw_answer in ZONE_A_SYNONYMS:
            return "zone_a"
        if raw_answer in ZONE_B_SYNONYMS:
            return "zone_b"
        if raw_answer in EQUAL_SYNONYMS:
            return "equal"

        # Explicitly reject unrecognized answers instead of silently falling back
        raise ValueError(
            f"Unrecognized ground-truth zone comparison answer '{raw_answer}' "
            f"for comparison '{comparison_id or 'default'}' in scene '{scene.scene_id}'. "
            f"Expected 'zone_a', 'zone_b', 'equal' (or supported synonyms: {sorted(ZONE_A_SYNONYMS | ZONE_B_SYNONYMS | EQUAL_SYNONYMS)})."
        )

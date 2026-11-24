from abc import ABC, abstractmethod
from typing import Literal

from dl.contracts.enums import Verdict
from dl.contracts.scene import Box, Scene
from dl.contracts.vision import SceneAnalysis

# Allowed outcomes when comparing hazards between two zones
ZoneComparisonResult = Literal["zone_a", "zone_b", "equal"]


class VisionAdapter(ABC):
    """
    Abstract interface for Vision AI adapters in DisasterLens.

    Provides a standardized contract for all vision model implementations:
    - Real multimodal LLM APIs (e.g., Gemini, backup providers)
    - Offline cached responses for replay and cost control
    - Ground-truth oracle mock implementations

    CRITICAL DATA-LEAKAGE / INTEGRITY RULE:
    The `scene` input object contains `ground_truth`. Live AI model adapters
    must NEVER pass `scene.ground_truth` to the external AI model or prompt.
    Real providers must only use `image_bytes` and unprivileged geometric layout
    (such as segment IDs, centerlines, and node coordinates). Only the oracle
    mock (`MockVisionAdapter`) is allowed to read `scene.ground_truth`.
    """

    @abstractmethod
    def analyze_scene(
        self,
        image_bytes: bytes,
        scene: Scene,
        prompt_version: str = "v1",
    ) -> SceneAnalysis:
        """
        Analyze an aerial disaster scene image for visible hazards and road statuses.

        Args:
            image_bytes: Raw binary content of the scene image (PNG or JPEG).
            scene: Complete Scene object providing road network layout and scene ID.
                   NOTE: Real providers must never expose scene.ground_truth to external AI models.
                         Only MockVisionAdapter is permitted to inspect ground_truth.
            prompt_version: Version tag of the prompt to use (e.g., 'v1', 'v2').

        Returns:
            SceneAnalysis: Validated Pydantic contract object containing predicted hazards,
                           segment verdicts, damaged building count, water regions,
                           and execution telemetry.
        """
        pass

    @abstractmethod
    def answer_route_questions(
        self,
        image_bytes: bytes,
        questions: dict[str, str],
        scene: Scene,
        prompt_version: str = "v1",
    ) -> dict[str, Verdict]:
        """
        Determine whether routes between specific intersections are obstructed.

        Args:
            image_bytes: Raw binary content of the scene image.
            questions: Mapping of question ID (e.g., 'Q-004') to the route question text.
            scene: Complete Scene object providing road network topology.
                   NOTE: Real providers must never expose scene.ground_truth to external AI models.
                         Only MockVisionAdapter is permitted to read ground_truth.route_questions.
            prompt_version: Version tag of the question-answering prompt.

        Returns:
            dict[str, Verdict]: Mapping of question ID to Verdict.CLEAR or Verdict.OBSTRUCTED.
        """
        pass

    @abstractmethod
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
        Compare two geographic zones to evaluate which contains more visible hazards.

        Args:
            image_bytes: Raw binary content of the scene image.
            zone_a: Bounding box [x1, y1, x2, y2] defining Zone A.
            zone_b: Bounding box [x1, y1, x2, y2] defining Zone B.
            scene: Complete Scene object.
                   NOTE: Real providers must never expose scene.ground_truth to external AI models.
                         Only MockVisionAdapter is permitted to read ground_truth.zone_comparisons.
            comparison_id: Identifier of the zone comparison question (e.g., 'Z-01').
            prompt_version: Version tag of the comparison prompt.

        Returns:
            ZoneComparisonResult: 'zone_a', 'zone_b', or 'equal' indicating which zone has
                                  more visible hazard area.
        """
        pass

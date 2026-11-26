"""Generator domain models and adapters to canonical shared contracts.

Imports shared enums and contract schemas from ``dl.contracts`` (owned by
Rishikesh) and provides rich internal models for geometry, placement specs,
question generation, and rendering, along with converters to ``dl.contracts.scene.Scene``
and ``dl.contracts.evaluation.EvaluationDatasetScene``.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from dl.contracts.enums import Difficulty, HazardType, RoadStatus
from dl.contracts.scene import (
    Box,
)
from dl.contracts.scene import (
    GroundTruth as ContractGroundTruth,
)
from dl.contracts.scene import (
    Hazard as ContractHazard,
)
from dl.contracts.scene import (
    RoadNode as ContractRoadNode,
)
from dl.contracts.scene import (
    RoadSegment as ContractRoadSegment,
)
from dl.contracts.scene import (
    Scene as ContractScene,
)


class PlacementSpec(str, Enum):
    BLOCK_FULL = "block_full"
    BLOCK_PARTIAL = "block_partial"
    NEAR_MISS_DECOY = "near_miss_decoy"
    WATER_ON_PARK = "water_on_park"
    DAMAGED_BUILDING_ONLY = "damaged_building_only"
    BUILDING_SPILL = "building_spill"
    ROAD_DAMAGE = "road_damage"


class Severity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"


class Zone(str, Enum):
    NW = "NW"
    NE = "NE"
    SW = "SW"
    SE = "SE"


class Point(BaseModel):
    x: float
    y: float


class BBox(BaseModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def to_box(self) -> Box:
        return Box((self.x_min, self.y_min, self.x_max, self.y_max))


class Intersection(BaseModel):
    id: str = Field(..., pattern=r"^N\d+$")
    x: float
    y: float
    zone: Zone


class RoadSegment(BaseModel):
    id: str = Field(..., pattern=r"^SEG-\d{3}$")
    node_a: str
    node_b: str
    centerline: list[Point]
    polygon: list[Point]
    length_m: float
    width_px: float
    zone: Zone


class Building(BaseModel):
    id: str = Field(..., pattern=r"^B-\d{3}$")
    polygon: list[Point]
    zone: Zone


class Park(BaseModel):
    id: str = Field(..., pattern=r"^P-\d{3}$")
    polygon: list[Point]
    zone: Zone


class Hazard(BaseModel):
    id: str = Field(..., pattern=r"^H-\d{3}$")
    type: HazardType
    placement: PlacementSpec
    polygon: list[Point]
    bbox: BBox
    severity: Severity | None = None
    affected_road: str | None = None
    affected_building: str | None = None


class Scene(BaseModel):
    """Complete synthetic disaster-city scene (generator representation)."""

    scene_id: str = Field(..., pattern=r"^(?:S-\d{4}|S-TEST.*|DEMO-\d{3})$")
    seed: int
    difficulty: Difficulty
    grid_size: int = Field(..., ge=4, le=6)
    image_width: int = 1024
    image_height: int = 1024
    pixel_to_metre: float = Field(
        default=0.2,
        description="1 pixel ≈ 0.2 metres",
    )
    intersections: list[Intersection]
    road_segments: list[RoadSegment]
    buildings: list[Building]
    parks: list[Park]
    hazards: list[Hazard]


class SegmentGroundTruth(BaseModel):
    segment_id: str
    status: RoadStatus
    max_coverage: float
    blocking_hazards: list[str] = Field(default_factory=list)


class GroundTruth(BaseModel):
    """Ground-truth road statuses and aggregated damage info for a scene."""

    scene_id: str
    segment_statuses: list[SegmentGroundTruth]
    damaged_building_ids: list[str] = Field(default_factory=list)
    water_region_ids: list[str] = Field(default_factory=list)
    hazard_area_per_zone: dict[str, float] = Field(default_factory=dict)


class QuestionType(str, Enum):
    BLOCKED_SEGMENTS = "blocked_segments"
    DAMAGED_BUILDINGS = "damaged_buildings"
    WATER_REGIONS = "water_regions"
    ROUTE_OBSTRUCTION_POSITIVE = "route_obstruction_positive"
    ROUTE_OBSTRUCTION_NEGATIVE = "route_obstruction_negative"
    ZONE_COMPARISON = "zone_comparison"


class Question(BaseModel):
    id: str
    type: QuestionType
    prompt: str
    expected_answer: dict


class QuestionSet(BaseModel):
    scene_id: str
    questions: list[Question]


def _extract_route_key(question: Question) -> str:
    """Extract 'NA-NB' route key from a route question prompt or fallback to question id."""
    tokens = question.prompt.replace("?", "").split()
    nodes = [tok for tok in tokens if tok.startswith("N") and tok[1:].isdigit()]
    if len(nodes) >= 2:
        return f"{nodes[0]}-{nodes[1]}"
    return question.id


def to_contract_scene(
    scene: Scene,
    gt: GroundTruth,
    qs: QuestionSet,
    split: Literal["dev", "test"] = "dev",
) -> ContractScene:
    """Convert generator models into the canonical ``dl.contracts.scene.Scene``."""
    nodes = [
        ContractRoadNode(node_id=inter.id, x=inter.x, y=inter.y)
        for inter in scene.intersections
    ]
    segments = [
        ContractRoadSegment(
            segment_id=seg.id,
            from_node=seg.node_a,
            to_node=seg.node_b,
            length=seg.length_m,
            centerline=[(p.x, p.y) for p in seg.centerline],
            polygon=[(p.x, p.y) for p in seg.polygon],
        )
        for seg in scene.road_segments
    ]
    contract_hazards = [
        ContractHazard(
            hazard_id=h.id,
            type=h.type,
            bbox=h.bbox.to_box(),
            polygon=[(p.x, p.y) for p in h.polygon],
        )
        for h in scene.hazards
    ]

    seg_status_map: dict[str, Literal["blocked", "partial", "clear"]] = {}
    for s in gt.segment_statuses:
        val = s.status.value
        if val in ("blocked", "partial", "clear"):
            seg_status_map[s.segment_id] = val  # type: ignore[assignment]
        else:
            seg_status_map[s.segment_id] = "clear"

    water_boxes = [
        h.bbox.to_box() for h in scene.hazards if h.id in set(gt.water_region_ids)
    ]

    route_answers: dict[str, Literal["obstructed", "clear"]] = {}
    zone_comparisons: dict[str, str] = {}
    for q in qs.questions:
        if q.type in (
            QuestionType.ROUTE_OBSTRUCTION_POSITIVE,
            QuestionType.ROUTE_OBSTRUCTION_NEGATIVE,
        ):
            rkey = _extract_route_key(q)
            route_answers[rkey] = (
                "obstructed" if q.expected_answer.get("obstructed") else "clear"
            )
        elif q.type == QuestionType.ZONE_COMPARISON:
            za = q.expected_answer.get("zone_a", "")
            zb = q.expected_answer.get("zone_b", "")
            winner = q.expected_answer.get("zone_with_more", "")
            if za and zb and winner:
                zone_comparisons[f"{za}-{zb}"] = winner

    contract_gt = ContractGroundTruth(
        hazards=contract_hazards,
        segment_status=seg_status_map,
        damaged_building_count=len(gt.damaged_building_ids),
        water_regions=water_boxes,
        route_questions=route_answers,
        zone_comparisons=zone_comparisons,
    )

    return ContractScene(
        scene_id=scene.scene_id,
        difficulty=scene.difficulty,
        split=split,
        seed=scene.seed,
        image_width=scene.image_width,
        image_height=scene.image_height,
        nodes=nodes,
        segments=segments,
        hazards=contract_hazards,
        ground_truth=contract_gt,
    )


def to_evaluation_record(
    scene: Scene,
    gt: GroundTruth,
    qs: QuestionSet,
    split: Literal["dev", "test"] = "dev",
) -> dict:
    """Convert generator models into an ``EvaluationDatasetScene`` dict."""
    cs = to_contract_scene(scene, gt, qs, split=split)
    near_miss_segs = sorted(
        {
            h.affected_road
            for h in scene.hazards
            if h.placement == PlacementSpec.NEAR_MISS_DECOY and h.affected_road
        }
    )
    near_miss_questions: list[str] = []
    route_pairs: list[dict[str, str]] = []
    for q in qs.questions:
        if q.type in (
            QuestionType.ROUTE_OBSTRUCTION_POSITIVE,
            QuestionType.ROUTE_OBSTRUCTION_NEGATIVE,
        ):
            rkey = _extract_route_key(q)
            parts = rkey.split("-")
            if len(parts) == 2:
                route_pairs.append({"origin": parts[0], "destination": parts[1]})
            if q.type == QuestionType.ROUTE_OBSTRUCTION_NEGATIVE:
                near_miss_questions.append(rkey)

    return {
        "scene_id": cs.scene_id,
        "difficulty": cs.difficulty.value,
        "split": cs.split,
        "near_miss_segments": near_miss_segs,
        "near_miss_questions": near_miss_questions,
        "truth": {
            "hazards": [
                {"type": h.type.value, "bbox": list(h.bbox.root)} for h in cs.hazards
            ],
            "segments": dict(cs.ground_truth.segment_status),
            "damaged_building_count": cs.ground_truth.damaged_building_count,
            "water_regions": [
                {"bbox": list(box.root)} for box in cs.ground_truth.water_regions
            ],
            "routes": dict(cs.ground_truth.route_questions),
            "zone_comparisons": dict(cs.ground_truth.zone_comparisons),
        },
        "road_graph": {
            "segments": [
                {
                    "id": seg.id,
                    "from": seg.node_a,
                    "to": seg.node_b,
                    "length": seg.length_m,
                }
                for seg in scene.road_segments
            ],
            "routes": route_pairs,
        },
    }

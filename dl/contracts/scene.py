from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from dl.contracts.enums import Difficulty, HazardType


class Box(RootModel[tuple[float, float, float, float]]):
    """Shared [x1, y1, x2, y2] pixel-box format."""

    @model_validator(mode="after")
    def ordered_coordinates(self):
        if not all(isfinite(value) for value in self.root):
            raise ValueError("box coordinates must be finite")
        if self.root[2] < self.root[0] or self.root[3] < self.root[1]:
            raise ValueError("box coordinates must be ordered")
        return self


class Hazard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hazard_id: str
    type: HazardType
    bbox: Box
    polygon: list[tuple[float, float]] = Field(default_factory=list)


class RoadNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    x: float
    y: float


class RoadSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    from_node: str
    to_node: str
    length: float = Field(gt=0)
    centerline: list[tuple[float, float]] = Field(min_length=2)
    polygon: list[tuple[float, float]] = Field(default_factory=list)


class GroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hazards: list[Hazard] = Field(default_factory=list)
    segment_status: dict[str, Literal["blocked", "partial", "clear"]] = Field(default_factory=dict)
    damaged_building_count: int = Field(ge=0)
    water_regions: list[Box] = Field(default_factory=list)
    route_questions: dict[str, Literal["obstructed", "clear"]] = Field(default_factory=dict)
    zone_comparisons: dict[str, str] = Field(default_factory=dict)


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    difficulty: Difficulty
    split: Literal["dev", "test"]
    seed: int
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    nodes: list[RoadNode]
    segments: list[RoadSegment]
    hazards: list[Hazard] = Field(default_factory=list)
    ground_truth: GroundTruth

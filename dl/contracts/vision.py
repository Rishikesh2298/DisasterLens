from pydantic import BaseModel, ConfigDict, Field

from dl.contracts.enums import HazardType, RoadStatus
from dl.contracts.scene import Box


class PredictedHazard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: HazardType
    bbox: Box
    confidence: float = Field(ge=0, le=1)


class SegmentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: RoadStatus
    confidence: float = Field(ge=0, le=0.85)
    evidence: str = ""
    visible: bool | None = None


class SceneAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    hazards: list[PredictedHazard] = Field(default_factory=list)
    segment_verdicts: dict[str, SegmentVerdict] = Field(default_factory=dict)
    damaged_building_count: int | None = Field(default=None, ge=0)
    water_regions: list[Box] = Field(default_factory=list)
    image_quality_good: bool | None = None
    model_id: str
    prompt_version: str
    valid_json: bool = True
    latency_ms: int | None = Field(default=None, ge=0)

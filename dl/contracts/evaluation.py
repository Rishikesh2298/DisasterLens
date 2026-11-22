from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from dl.contracts.enums import Difficulty, RoadStatus
from dl.contracts.scene import Box


class MetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str
    metrics: dict[str, float | int | None]
    details: dict[str, Any] = Field(default_factory=dict)


class FailureCase(BaseModel):
    scene_id: str
    category: str
    question: str | None = None
    prediction: Any = None
    truth: Any = None
    difficulty: str | None = None


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "0.1.0"
    run_name: str
    model_id: str
    prompt_version: str | None = None
    split: str
    is_mock: bool
    created_at: datetime
    scene_count: int = Field(ge=0)
    metrics: dict[str, MetricResult]
    route_impact: dict[str, Any] = Field(default_factory=dict)
    failures: list[FailureCase] = Field(default_factory=list)


class EvaluationHazard(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    bbox: Box
    confidence: float | None = Field(default=None, ge=0, le=1)


class EvaluationRegion(BaseModel):
    model_config = ConfigDict(extra="allow")
    bbox: Box


class EvaluationGroundTruth(BaseModel):
    model_config = ConfigDict(extra="allow")
    hazards: list[EvaluationHazard] = Field(default_factory=list)
    segments: dict[str, Literal["blocked", "partial", "clear"]] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("segments", "segment_status"),
    )
    damaged_building_count: int = Field(default=0, ge=0)
    water_regions: list[EvaluationRegion] = Field(default_factory=list)
    routes: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("routes", "route_answers"),
    )
    zone_comparisons: dict[str, str] = Field(default_factory=dict)


class EvaluationDatasetScene(BaseModel):
    model_config = ConfigDict(extra="allow")
    scene_id: str
    split: Literal["dev", "test"]
    difficulty: Difficulty | None = None
    truth: EvaluationGroundTruth = Field(validation_alias=AliasChoices("truth", "ground_truth"))


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="allow")
    scenes: list[EvaluationDatasetScene]


class EvaluationPrediction(BaseModel):
    model_config = ConfigDict(extra="allow")
    hazards: list[EvaluationHazard] = Field(default_factory=list)
    segments: dict[str, RoadStatus] = Field(default_factory=dict)
    segment_details: dict[str, dict[str, float]] = Field(default_factory=dict)
    damaged_building_count: int | None = Field(default=None, ge=0)
    water_regions: list[EvaluationRegion] = Field(default_factory=list)
    routes: dict[str, str] = Field(default_factory=dict)
    zone_comparisons: dict[str, str] = Field(default_factory=dict)
    valid_json: bool = True
    latency_ms: int | None = Field(default=None, ge=0)


class EvaluationPredictionScene(BaseModel):
    model_config = ConfigDict(extra="allow")
    scene_id: str
    prediction: EvaluationPrediction


class EvaluationPredictionFile(BaseModel):
    model_config = ConfigDict(extra="allow")
    scenes: list[EvaluationPredictionScene]
    model_id: str | None = None
    prompt_version: str | None = None
    is_mock: bool = False

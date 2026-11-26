from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from dl.contracts.enums import RoadStatus


class SegmentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: str
    scene_id: str
    segment_id: str
    captured_at: datetime
    uploaded_at: datetime
    analyzed_at: datetime
    source: str
    confidence: float = Field(ge=0, le=0.85)
    status: RoadStatus
    evidence: str = ""


class SegmentState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    status: RoadStatus
    captured_at: datetime | None = None
    age_hours: float | None = Field(default=None, ge=0)
    warning: str | None = None

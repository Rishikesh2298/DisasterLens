from pydantic import BaseModel, ConfigDict, Field

from dl.contracts.enums import RoadStatus


class RoutePath(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_ids: list[str]
    segment_ids: list[str]
    distance: float = Field(ge=0)


class RouteRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str
    destination: str
    primary_route: RoutePath | None
    alternative_routes: list[RoutePath] = Field(default_factory=list)
    affected_segments: dict[str, RoadStatus] = Field(default_factory=dict)
    explanation: str
    generated_at: str

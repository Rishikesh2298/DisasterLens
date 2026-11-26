"""
Shared Pydantic v2 contracts for DisasterLens scenes.

Combines Tejash/Rajneesh scene contracts with Rishikesh's Box and RoadNode
definitions required by evaluation and vision contracts.

All geometry uses pixel coordinates on a 1024×1024 canvas.
Scale: 1 pixel ≈ 0.2 metres (documented in city.py).
"""

from __future__ import annotations

from enum import Enum
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RoadStatus(str, Enum):
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    CLEAR = "CLEAR"
    UNCERTAIN = "UNCERTAIN"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class HazardType(str, Enum):
    FLOOD = "flood"
    DEBRIS = "debris"
    FALLEN_TREE = "fallen_tree"
    ROAD_DAMAGE = "road_damage"
    DAMAGED_BUILDING = "damaged_building"


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


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------

class Point(BaseModel):
    x: float
    y: float


class Box(RootModel[tuple[float, float, float, float]]):
    """Shared [x1, y1, x2, y2] pixel-box format."""

    @model_validator(mode="after")
    def ordered_coordinates(self):
        if not all(isfinite(value) for value in self.root):
            raise ValueError("box coordinates must be finite")
        if self.root[2] < self.root[0] or self.root[3] < self.root[1]:
            raise ValueError("box coordinates must be ordered")
        return self


class RoadNode(BaseModel):
    """Lightweight graph node contract compatible with benchmark evaluation."""

    model_config = ConfigDict(extra="forbid")
    node_id: str
    x: float
    y: float


class BBox(BaseModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float


# ---------------------------------------------------------------------------
# City elements
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Hazards
# ---------------------------------------------------------------------------

class Hazard(BaseModel):
    id: str = Field(..., pattern=r"^H-\d{3}$")
    type: HazardType
    placement: PlacementSpec
    polygon: list[Point]
    bbox: BBox
    severity: Severity | None = None
    affected_road: str | None = None
    affected_building: str | None = None


# ---------------------------------------------------------------------------
# Scene (top-level)
# ---------------------------------------------------------------------------

class Scene(BaseModel):
    """Complete synthetic disaster-city scene."""

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


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

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
    # Hidden answer — never included in model-visible content
    expected_answer: dict


class QuestionSet(BaseModel):
    scene_id: str
    questions: list[Question]

from enum import StrEnum


class HazardType(StrEnum):
    FLOOD = "flood"
    DEBRIS = "debris"
    FALLEN_TREE = "fallen_tree"
    ROAD_DAMAGE = "road_damage"
    DAMAGED_BUILDING = "damaged_building"


class RoadStatus(StrEnum):
    BLOCKED = "blocked"
    PARTIAL = "partial"
    CLEAR = "clear"
    UNCERTAIN = "uncertain"
    STALE = "stale"
    UNKNOWN = "unknown"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Verdict(StrEnum):
    CLEAR = "clear"
    OBSTRUCTED = "obstructed"

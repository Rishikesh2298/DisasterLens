"""
Shared Pydantic v2 data contracts for DisasterLens routing engine.

Independent of FastAPI and database frameworks.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from dl.contracts.scene import RoadStatus

SYNTHETIC_DATA_DISCLAIMER = (
    "DisasterLens is a research prototype evaluating synthetic disaster scenes. "
    "It is not a certified navigation or emergency-response system. "
    "A road marked 'CLEAR' indicates only that no obstruction was detected at capture time."
)


class RouteStep(BaseModel):
    """Single segment traversal step in a route."""

    segment_id: str = Field(..., description="Segment identifier, e.g. SEG-001")
    from_node: str = Field(..., description="Origin node for this step, e.g. N1")
    to_node: str = Field(..., description="Destination node for this step, e.g. N2")
    length_m: float = Field(..., description="Physical road length in metres")
    effective_status: RoadStatus = Field(..., description="Effective road condition at query time")
    freshness: str = Field(..., description="'fresh', 'ageing', 'stale', or 'unknown'")
    cost_multiplier: float = Field(..., description="Applied cost multiplier, e.g. 1.0, 1.5, 3.0, 4.0, 8.0")
    effective_cost: float = Field(..., description="Traversed edge cost = length_m * cost_multiplier")
    is_stale_from_blocked: bool = Field(
        default=False, description="Whether this segment is STALE originating from a BLOCKED observation"
    )
    age_hours: float | None = Field(default=None, description="Observation age in hours relative to as_of")
    hazard_type: str | None = Field(default=None, description="Reported hazard type if known")


class RouteAlternative(BaseModel):
    """A candidate route path connecting origin to destination."""

    rank: int = Field(default=1, description="1 for primary recommended route, 2+ for alternative paths")
    is_baseline: bool = Field(default=False, description="True if this is the physical shortest-distance baseline")
    node_path: list[str] = Field(default_factory=list, description="Ordered sequence of node IDs: ['N1', 'N2', ...]")
    segment_path: list[str] = Field(default_factory=list, description="Ordered sequence of segment IDs: ['SEG-001', ...]")
    total_length_m: float = Field(default=0.0, description="Total physical road length in metres")
    total_cost: float = Field(default=0.0, description="Total weighted traversal cost")
    unverified_segments_count: int = Field(default=0, description="Count of UNKNOWN or STALE segments on path")
    has_fresh_blocked: bool = Field(default=False, description="True if any segment on path is fresh BLOCKED")
    is_valid: bool = Field(default=True, description="True if route passes all verification constraints")
    steps: list[RouteStep] = Field(default_factory=list, description="Detailed per-segment traversal steps")


class RouteVerification(BaseModel):
    """Topological, continuity, and safety validation of a route."""

    is_valid: bool = Field(..., description="True if all verification checks pass")
    is_connected: bool = Field(..., description="True if each step is a valid continuous edge in the graph")
    starts_at_origin: bool = Field(..., description="True if route starts at requested origin")
    ends_at_destination: bool = Field(..., description="True if route ends at requested destination")
    has_fresh_blocked_segments: bool = Field(..., description="True if path traverses any fresh BLOCKED road")
    blocked_segment_ids: list[str] = Field(default_factory=list, description="List of fresh BLOCKED segment IDs on path")
    unverified_segment_ids: list[str] = Field(default_factory=list, description="List of UNKNOWN or STALE segment IDs on path")
    unverified_count: int = Field(default=0, description="Total count of unverified segments")
    failure_reasons: list[str] = Field(default_factory=list, description="Machine-readable failure reason codes")


class RouteRecommendation(BaseModel):
    """Complete route recommendation engine response."""

    origin: str = Field(..., description="Origin node ID, e.g. N1")
    destination: str = Field(..., description="Destination node ID, e.g. N36")
    as_of: datetime = Field(..., description="Reference timestamp used for evaluation")
    risk_mode: str = Field(default="normal", description="Risk mode: 'normal'")

    baseline_route: RouteAlternative | None = Field(
        default=None, description="Physical shortest path by length ignoring road condition multipliers"
    )
    recommended_route: RouteAlternative | None = Field(
        default=None, description="Cheapest condition-aware route strictly avoiding fresh BLOCKED roads"
    )
    alternatives: list[RouteAlternative] = Field(
        default_factory=list, description="Up to 2 additional valid distinct routes"
    )

    verification: RouteVerification = Field(
        ..., description="Verification result for the recommended route (or failure report if none)"
    )
    explanation: str = Field(..., description="Deterministic templated explanation of routing decisions")
    warnings: list[str] = Field(default_factory=list, description="Advisory warnings for unverified or stale roads")
    disclaimer: str = Field(default=SYNTHETIC_DATA_DISCLAIMER, description="Mandatory safety notice")

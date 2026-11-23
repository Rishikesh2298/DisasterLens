"""
Routing edge cost multipliers for DisasterLens.

Calculates edge traversal weights based on effective road condition and freshness.
Fresh BLOCKED roads are excluded from routing graphs.
"""

from __future__ import annotations

from dl.contracts.scene import RoadStatus
from dl.routing.freshness import EffectiveRoadStatus

# Multipliers mandated by the routing specification:
# CLEAR fresh: 1.0
# CLEAR ageing: 1.5
# CLEAR stale: 3.0
# PARTIAL: 1.5 (active)
# UNCERTAIN: 4.0 (active)
# UNKNOWN: 3.0
# STALE from BLOCKED: 8.0 (avoided, heavily penalised)
# Fresh BLOCKED: None / infinite (excluded from routing graph)


def get_cost_multiplier(
    status: RoadStatus | str,
    freshness: str = "fresh",
    is_stale_from_blocked: bool = False,
) -> float | None:
    """
    Returns the edge cost multiplier based on status and freshness.

    Returns:
        float multiplier if traversable, or None if the edge is fresh BLOCKED
        (indicating the edge must be omitted from routing graph).
    """
    if isinstance(status, str):
        status = RoadStatus(status)

    if status == RoadStatus.BLOCKED:
        # Fresh BLOCKED: exclude edge from route graph
        return None

    if is_stale_from_blocked:
        # STALE originating from BLOCKED observation: 8.0 multiplier
        return 8.0

    if status == RoadStatus.CLEAR:
        if freshness == "fresh":
            return 1.0
        elif freshness == "ageing":
            return 1.5
        else:  # stale
            return 3.0

    elif status == RoadStatus.PARTIAL:
        if freshness in ("fresh", "active"):
            return 1.5
        else:  # stale
            return 3.0

    elif status == RoadStatus.UNCERTAIN:
        if freshness in ("fresh", "active"):
            return 4.0
        else:  # unknown
            return 3.0

    elif status == RoadStatus.UNKNOWN:
        return 3.0

    elif status == RoadStatus.STALE:
        # Ordinary STALE (e.g. from clear or partial): 3.0
        return 3.0

    return 3.0


def compute_edge_cost(
    length_m: float,
    status: RoadStatus | str,
    freshness: str = "fresh",
    is_stale_from_blocked: bool = False,
) -> float | None:
    """
    Computes effective traversal cost: length_m * multiplier.

    Returns None if edge is fresh BLOCKED.
    """
    multiplier = get_cost_multiplier(
        status=status,
        freshness=freshness,
        is_stale_from_blocked=is_stale_from_blocked,
    )
    if multiplier is None:
        return None
    return float(length_m) * multiplier


def compute_edge_cost_from_effective(
    length_m: float,
    effective: EffectiveRoadStatus,
) -> float | None:
    """
    Computes effective traversal cost directly from an EffectiveRoadStatus instance.
    """
    return compute_edge_cost(
        length_m=length_m,
        status=effective.status,
        freshness=effective.freshness,
        is_stale_from_blocked=effective.is_stale_from_blocked,
    )

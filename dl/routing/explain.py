"""
Deterministic route explanation and warning generator for DisasterLens.

Produces template-based explanations for route recommendations and detours.
Adheres strictly to research safety wording (never uses the word 'safe',
uses 'No obstruction detected' for CLEAR, and includes prototype disclaimers).
"""

from __future__ import annotations

from dl.contracts.observation import RoadStatus
from dl.contracts.routing import RouteAlternative
from dl.routing.freshness import EffectiveRoadStatus


def build_route_explanation(
    origin: str,
    destination: str,
    baseline: RouteAlternative | None,
    recommended: RouteAlternative | None,
    segment_states: dict[str, EffectiveRoadStatus] | None = None,
) -> str:
    """
    Generates a deterministic explanation of the routing outcome from actual route data.
    """
    # Case 1: Same node
    if origin == destination:
        return (
            f"Origin and destination are identical ({origin}). "
            "Zero traversal distance required. No obstruction detected."
        )

    # Case 2: No valid recommended route exists
    if recommended is None or not recommended.is_valid:
        if baseline is not None and baseline.has_fresh_blocked:
            blocked_steps = [
                s.segment_id for s in baseline.steps if s.effective_status == RoadStatus.BLOCKED
            ]
            return (
                f"No viable route found connecting {origin} to {destination}. "
                f"The shortest path is obstructed by confirmed blockage on segment(s): {', '.join(blocked_steps)}. "
                "No alternative path avoiding fresh blocked roads is currently reachable in the network."
            )
        return (
            f"No viable route found connecting {origin} to {destination}. "
            "The network graph cannot establish a connected path between these intersections."
        )

    # If baseline is missing or equal to recommended
    if baseline is None or baseline.segment_path == recommended.segment_path:
        unverified_txt = ""
        if recommended.unverified_segments_count > 0:
            unverified_txt = (
                f" Note: {recommended.unverified_segments_count} of {len(recommended.segment_path)} "
                "segments rely on stale or unobserved imagery."
            )
        return (
            f"The recommended route follows the shortest path ({recommended.total_length_m:.1f} m "
            f"across {len(recommended.segment_path)} segments). "
            f"No obstruction detected on the active corridor.{unverified_txt}"
        )

    # Recommended route diverged from baseline (a detour was taken)
    delta_m = recommended.total_length_m - baseline.total_length_m
    delta_pct = (delta_m / baseline.total_length_m * 100.0) if baseline.total_length_m > 0 else 0.0

    # Reason for detour: check if baseline has fresh BLOCKED edges
    blocked_baseline_steps = [
        s for s in baseline.steps if s.effective_status == RoadStatus.BLOCKED
    ]

    if blocked_baseline_steps:
        reasons: list[str] = []
        for s in blocked_baseline_steps:
            hazard = s.hazard_type or "debris or standing water"
            age_str = f"observed {s.age_hours:.1f}h ago" if s.age_hours is not None else "recently observed"
            reasons.append(f"{s.segment_id} ({hazard}, {age_str})")

        reasons_str = "; ".join(reasons)
        return (
            f"The shortest baseline route ({baseline.total_length_m:.1f} m) was avoided due to confirmed "
            f"obstruction on {reasons_str}. The recommended alternative ({recommended.total_length_m:.1f} m) "
            f"adds {delta_m:.1f} m (+{delta_pct:.1f}%) to ensure all chosen segments have no detected obstruction."
        )

    # Baseline was not strictly blocked, but higher cost (e.g. uncertain, partial, or stale from blocked)
    penalised_steps = [
        s for s in baseline.steps if s.effective_status in (RoadStatus.UNCERTAIN, RoadStatus.PARTIAL) or s.is_stale_from_blocked
    ]
    if penalised_steps:
        penalised_ids = ", ".join(s.segment_id for s in penalised_steps)
        return (
            f"The shortest baseline path ({baseline.total_length_m:.1f} m) traverses penalised or uncertain "
            f"road segments ({penalised_ids}). The recommended route ({recommended.total_length_m:.1f} m) "
            f"adds {delta_m:.1f} m to prioritize corridors with clearer condition evidence."
        )

    return (
        f"The recommended route ({recommended.total_length_m:.1f} m) optimizes condition-weighted traversal, "
        f"adding {delta_m:.1f} m compared to the unweighted physical baseline ({baseline.total_length_m:.1f} m)."
    )


def build_route_warnings(
    route: RouteAlternative | None,
    segment_states: dict[str, EffectiveRoadStatus] | None = None,
) -> list[str]:
    """
    Constructs specific advisory warnings for unverified, stale, or heavily penalised segments.
    """
    warnings: list[str] = []
    if route is None:
        warnings.append("No viable route could be found connecting origin to destination.")
        return warnings

    if not route.is_valid:
        warnings.append("Route failed safety verification and must not be used for travel.")

    stale_blocked_segs = [s.segment_id for s in route.steps if s.is_stale_from_blocked]
    if stale_blocked_segs:
        warnings.append(
            f"Route traverses segment(s) previously reported BLOCKED over 24h ago with no recent updates: "
            f"{', '.join(stale_blocked_segs)}. Substantial residual hazard risk may remain."
        )

    uncertain_segs = [s.segment_id for s in route.steps if s.effective_status == RoadStatus.UNCERTAIN]
    if uncertain_segs:
        warnings.append(
            f"Route traverses segment(s) with conflicting or low-confidence evidence: {', '.join(uncertain_segs)}."
        )

    unverified_segs = [
        s.segment_id for s in route.steps if s.effective_status in (RoadStatus.UNKNOWN, RoadStatus.STALE) and not s.is_stale_from_blocked
    ]
    if unverified_segs:
        warnings.append(
            f"Route includes {len(unverified_segs)} unverified or stale segment(s) ({', '.join(unverified_segs)}). "
            "Road conditions have not been confirmed by recent imagery."
        )

    return warnings

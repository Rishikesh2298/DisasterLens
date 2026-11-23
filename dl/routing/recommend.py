"""
Route recommendation engine for DisasterLens.

Calculates:
  - Baseline shortest physical route (ignoring hazards).
  - Recommended condition-aware route (excluding fresh BLOCKED edges).
  - Up to two alternative routes via NetworkX k-shortest simple paths.
"""

from __future__ import annotations

from datetime import UTC, datetime

import networkx as nx

from dl.contracts.routing import (
    RouteAlternative,
    RouteRecommendation,
    RouteStep,
    RouteVerification,
)
from dl.contracts.scene import RoadStatus
from dl.routing.costs import get_cost_multiplier
from dl.routing.explain import build_route_explanation, build_route_warnings
from dl.routing.freshness import EffectiveRoadStatus
from dl.routing.graph import RoadGraph
from dl.routing.verify import verify_route


def _build_route_alternative(
    node_path: list[str],
    road_graph: RoadGraph,
    segment_states: dict[str, EffectiveRoadStatus],
    rank: int = 1,
    is_baseline: bool = False,
) -> RouteAlternative:
    """Helper to convert an ordered node path into a fully populated RouteAlternative."""
    if len(node_path) <= 1:
        return RouteAlternative(
            rank=rank,
            is_baseline=is_baseline,
            node_path=node_path,
            segment_path=[],
            total_length_m=0.0,
            total_cost=0.0,
            unverified_segments_count=0,
            has_fresh_blocked=False,
            is_valid=True,
            steps=[],
        )

    segment_path: list[str] = []
    steps: list[RouteStep] = []
    total_length = 0.0
    total_cost = 0.0
    unverified_count = 0
    has_fresh_blocked = False

    for i in range(len(node_path) - 1):
        u = node_path[i]
        v = node_path[i + 1]
        seg_id = road_graph.get_segment_for_edge(u, v)
        segment_path.append(seg_id)

        edge_data = road_graph.graph.get_edge_data(u, v)
        length_m = float(edge_data.get("length_m", 0.0))
        total_length += length_m

        st = segment_states.get(seg_id)
        if st is not None:
            eff_status = st.status
            freshness = st.freshness
            age_hours = st.age_hours
            is_stale_blocked = st.is_stale_from_blocked
            hazard_type = getattr(st, "hazard_type", None)

            mult = get_cost_multiplier(
                status=eff_status,
                freshness=freshness,
                is_stale_from_blocked=is_stale_blocked,
            )
            if mult is None:
                has_fresh_blocked = True
                mult = 1.0  # fallback multiplier for tracking baseline length

            if eff_status in (RoadStatus.UNKNOWN, RoadStatus.STALE) or freshness == "unknown":
                unverified_count += 1
        else:
            eff_status = RoadStatus.UNKNOWN
            freshness = "unknown"
            age_hours = None
            is_stale_blocked = False
            hazard_type = None
            mult = 3.0
            unverified_count += 1

        cost = length_m * mult
        total_cost += cost

        steps.append(
            RouteStep(
                segment_id=seg_id,
                from_node=u,
                to_node=v,
                length_m=length_m,
                effective_status=eff_status,
                freshness=freshness,
                cost_multiplier=mult,
                effective_cost=cost,
                is_stale_from_blocked=is_stale_blocked,
                age_hours=age_hours,
                hazard_type=hazard_type,
            )
        )

    return RouteAlternative(
        rank=rank,
        is_baseline=is_baseline,
        node_path=node_path,
        segment_path=segment_path,
        total_length_m=round(total_length, 2),
        total_cost=round(total_cost, 2),
        unverified_segments_count=unverified_count,
        has_fresh_blocked=has_fresh_blocked,
        is_valid=not has_fresh_blocked if not is_baseline else True,
        steps=steps,
    )


def recommend(
    graph: RoadGraph,
    origin: str,
    destination: str,
    segment_states: dict[str, EffectiveRoadStatus] | None = None,
    as_of: datetime | None = None,
    risk_mode: str = "normal",
) -> RouteRecommendation:
    """
    Computes baseline and condition-aware recommended routes with up to 2 alternatives.

    Args:
        graph: Loaded RoadGraph network.
        origin: Origin intersection ID (e.g. 'N1').
        destination: Destination intersection ID (e.g. 'N36').
        segment_states: Mapping of segment_id -> EffectiveRoadStatus.
        as_of: Reference timestamp for evaluation.
        risk_mode: Routing risk profile ('normal').

    Returns:
        RouteRecommendation containing baseline, recommended route, alternatives,
        verification details, templated explanation, and advisory warnings.
    """
    eval_as_of = as_of or datetime.now(UTC)
    states = segment_states or {}

    # 1. Validate node existence
    if origin not in graph.graph:
        verification = RouteVerification(
            is_valid=False,
            is_connected=False,
            starts_at_origin=False,
            ends_at_destination=False,
            has_fresh_blocked_segments=False,
            blocked_segment_ids=[],
            unverified_segment_ids=[],
            unverified_count=0,
            failure_reasons=[f"ORIGIN_NOT_FOUND: node '{origin}' is not in graph"],
        )
        return RouteRecommendation(
            origin=origin,
            destination=destination,
            as_of=eval_as_of,
            risk_mode=risk_mode,
            baseline_route=None,
            recommended_route=None,
            alternatives=[],
            verification=verification,
            explanation=f"Cannot route: origin node '{origin}' does not exist in road network.",
            warnings=["Origin node not found."],
        )

    if destination not in graph.graph:
        verification = RouteVerification(
            is_valid=False,
            is_connected=False,
            starts_at_origin=False,
            ends_at_destination=False,
            has_fresh_blocked_segments=False,
            blocked_segment_ids=[],
            unverified_segment_ids=[],
            unverified_count=0,
            failure_reasons=[f"DESTINATION_NOT_FOUND: node '{destination}' is not in graph"],
        )
        return RouteRecommendation(
            origin=origin,
            destination=destination,
            as_of=eval_as_of,
            risk_mode=risk_mode,
            baseline_route=None,
            recommended_route=None,
            alternatives=[],
            verification=verification,
            explanation=f"Cannot route: destination node '{destination}' does not exist in road network.",
            warnings=["Destination node not found."],
        )

    # 2. Origin equals destination (same-node check)
    if origin == destination:
        point_alt = _build_route_alternative([origin], graph, states, rank=1, is_baseline=True)
        verif = verify_route(point_alt, graph, origin, destination, states)
        explanation = build_route_explanation(origin, destination, point_alt, point_alt, states)
        return RouteRecommendation(
            origin=origin,
            destination=destination,
            as_of=eval_as_of,
            risk_mode=risk_mode,
            baseline_route=point_alt,
            recommended_route=point_alt,
            alternatives=[],
            verification=verif,
            explanation=explanation,
            warnings=[],
        )

    # 3. Compute baseline route (shortest by physical distance length_m)
    baseline_alt: RouteAlternative | None = None
    try:
        baseline_nodes = nx.dijkstra_path(graph.graph, origin, destination, weight="length_m")
        baseline_alt = _build_route_alternative(
            baseline_nodes, graph, states, rank=1, is_baseline=True
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        baseline_alt = None

    # 4. Build condition-aware cost graph (fresh BLOCKED edges excluded)
    G_cost = nx.Graph()
    for node, data in graph.graph.nodes(data=True):
        G_cost.add_node(node, **data)

    for u, v, data in graph.graph.edges(data=True):
        seg_id = data.get("segment_id")
        length_m = float(data.get("length_m", 0.0))
        st = states.get(seg_id)

        if st is not None:
            mult = get_cost_multiplier(
                status=st.status,
                freshness=st.freshness,
                is_stale_from_blocked=st.is_stale_from_blocked,
            )
        else:
            mult = 3.0  # default UNKNOWN

        # If mult is None, edge is fresh BLOCKED -> EXCLUDE from G_cost
        if mult is not None:
            edge_cost = length_m * mult
            G_cost.add_edge(u, v, weight=edge_cost, length_m=length_m, segment_id=seg_id)

    # 5. Compute recommended route on G_cost
    recommended_alt: RouteAlternative | None = None
    alternatives: list[RouteAlternative] = []

    try:
        # NetworkX shortest_simple_paths yields paths in increasing cost order
        paths_generator = nx.shortest_simple_paths(G_cost, origin, destination, weight="weight")

        # Pick primary recommended route
        rec_nodes = next(paths_generator)
        recommended_alt = _build_route_alternative(rec_nodes, graph, states, rank=1, is_baseline=False)

        # Collect up to 2 distinct valid alternatives
        alt_rank = 2
        for alt_nodes in paths_generator:
            if alt_nodes == rec_nodes:
                continue

            candidate = _build_route_alternative(
                alt_nodes, graph, states, rank=alt_rank, is_baseline=False
            )
            # Verify candidate
            c_verif = verify_route(candidate, graph, origin, destination, states)
            if (
                c_verif.is_valid
                and candidate.segment_path != recommended_alt.segment_path
                and not any(a.segment_path == candidate.segment_path for a in alternatives)
            ):
                alternatives.append(candidate)
                alt_rank += 1
                if len(alternatives) >= 2:
                    break

    except (nx.NetworkXNoPath, nx.NodeNotFound, StopIteration):
        recommended_alt = None

    # 6. Verification
    if recommended_alt is not None:
        verification = verify_route(recommended_alt, graph, origin, destination, states)
    elif baseline_alt is not None:
        verification = verify_route(baseline_alt, graph, origin, destination, states)
    else:
        verification = RouteVerification(
            is_valid=False,
            is_connected=False,
            starts_at_origin=False,
            ends_at_destination=False,
            has_fresh_blocked_segments=False,
            blocked_segment_ids=[],
            unverified_segment_ids=[],
            unverified_count=0,
            failure_reasons=["NO_PATH_EXISTS"],
        )

    # 7. Explanations and warnings
    explanation = build_route_explanation(origin, destination, baseline_alt, recommended_alt, states)
    warnings = build_route_warnings(recommended_alt or baseline_alt, states)

    return RouteRecommendation(
        origin=origin,
        destination=destination,
        as_of=eval_as_of,
        risk_mode=risk_mode,
        baseline_route=baseline_alt,
        recommended_route=recommended_alt,
        alternatives=alternatives,
        verification=verification,
        explanation=explanation,
        warnings=warnings,
    )

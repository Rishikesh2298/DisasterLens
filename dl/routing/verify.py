"""
Route verification engine for DisasterLens.

Validates topological connectivity, endpoint consistency, and safety constraints
(excluding fresh BLOCKED edges and counting unverified roads).
"""

from __future__ import annotations

from dl.contracts.observation import RoadStatus
from dl.contracts.routing import RouteAlternative, RouteVerification
from dl.routing.freshness import EffectiveRoadStatus
from dl.routing.graph import RoadGraph


def verify_route(
    route: RouteAlternative,
    road_graph: RoadGraph,
    expected_origin: str,
    expected_destination: str,
    segment_states: dict[str, EffectiveRoadStatus] | None = None,
) -> RouteVerification:
    """
    Validates a proposed route against graph topology and road condition rules.

    Checks:
      1. Starts at expected origin.
      2. Ends at expected destination.
      3. Consecutive nodes form valid graph edges.
      4. Segment IDs match corresponding graph edges.
      5. Segment count is len(node_path) - 1.
      6. No fresh BLOCKED segment is traversed.
      7. Counts UNKNOWN and STALE segments as unverified.
      8. Flags STALE-from-BLOCKED segments.
    """
    failure_reasons: list[str] = []
    blocked_segment_ids: list[str] = []
    unverified_segment_ids: list[str] = []

    node_path = route.node_path
    segment_path = route.segment_path

    # Check empty path
    if not node_path:
        return RouteVerification(
            is_valid=False,
            is_connected=False,
            starts_at_origin=False,
            ends_at_destination=False,
            has_fresh_blocked_segments=False,
            blocked_segment_ids=[],
            unverified_segment_ids=[],
            unverified_count=0,
            failure_reasons=["EMPTY_ROUTE"],
        )

    # 1. Origin check
    starts_at_origin = node_path[0] == expected_origin
    if not starts_at_origin:
        failure_reasons.append(
            f"ORIGIN_MISMATCH: expected '{expected_origin}', got '{node_path[0]}'"
        )

    # 2. Destination check
    ends_at_destination = node_path[-1] == expected_destination
    if not ends_at_destination:
        failure_reasons.append(
            f"DESTINATION_MISMATCH: expected '{expected_destination}', got '{node_path[-1]}'"
        )

    # Handle single-node path (origin == destination)
    if len(node_path) == 1:
        if len(segment_path) != 0:
            failure_reasons.append("INCONSISTENT_SEGMENT_COUNT_FOR_POINT_ROUTE")
            is_valid = False
        else:
            is_valid = starts_at_origin and ends_at_destination

        return RouteVerification(
            is_valid=is_valid,
            is_connected=True,
            starts_at_origin=starts_at_origin,
            ends_at_destination=ends_at_destination,
            has_fresh_blocked_segments=False,
            blocked_segment_ids=[],
            unverified_segment_ids=[],
            unverified_count=0,
            failure_reasons=failure_reasons,
        )

    # 3. Path sequence consistency: len(node_path) must equal len(segment_path) + 1
    if len(node_path) != len(segment_path) + 1:
        failure_reasons.append(
            f"INCONSISTENT_LENGTH: {len(node_path)} nodes but {len(segment_path)} segments"
        )

    is_connected = True
    # 4. Topological connectivity and segment correspondence
    for i in range(len(node_path) - 1):
        u = node_path[i]
        v = node_path[i + 1]

        # Check edge exists in graph
        if not road_graph.graph.has_edge(u, v):
            is_connected = False
            failure_reasons.append(f"DISCONNECTED_EDGE: no graph edge between '{u}' and '{v}'")
            continue

        # If segment_path has this index, check segment ID matches edge
        if i < len(segment_path):
            expected_seg_id = segment_path[i]
            try:
                actual_seg_id = road_graph.get_segment_for_edge(u, v)
                if actual_seg_id != expected_seg_id:
                    failure_reasons.append(
                        f"SEGMENT_MISMATCH: edge ({u}, {v}) maps to '{actual_seg_id}', "
                        f"route recorded '{expected_seg_id}'"
                    )
            except KeyError:
                failure_reasons.append(f"UNKNOWN_EDGE: ({u}, {v})")

    # 5. Check condition states on segment path
    states = segment_states or {}
    for seg_id in segment_path:
        st = states.get(seg_id)
        if st is not None:
            # Fresh BLOCKED check
            if st.status == RoadStatus.BLOCKED and not st.is_stale_from_blocked:
                blocked_segment_ids.append(seg_id)
            # Unverified check: UNKNOWN or STALE
            if st.status in (RoadStatus.UNKNOWN, RoadStatus.STALE) or st.freshness == "unknown":
                unverified_segment_ids.append(seg_id)
        else:
            # If no state provided, default segment to unverified (UNKNOWN)
            unverified_segment_ids.append(seg_id)

    has_fresh_blocked = len(blocked_segment_ids) > 0
    if has_fresh_blocked:
        failure_reasons.append(f"CONTAINS_FRESH_BLOCKED: segments {blocked_segment_ids}")

    # Route is valid only if all checks pass and there are no failure reasons
    is_valid = (
        starts_at_origin
        and ends_at_destination
        and is_connected
        and not has_fresh_blocked
        and len(failure_reasons) == 0
    )

    return RouteVerification(
        is_valid=is_valid,
        is_connected=is_connected,
        starts_at_origin=starts_at_origin,
        ends_at_destination=ends_at_destination,
        has_fresh_blocked_segments=has_fresh_blocked,
        blocked_segment_ids=blocked_segment_ids,
        unverified_segment_ids=unverified_segment_ids,
        unverified_count=len(unverified_segment_ids),
        failure_reasons=failure_reasons,
    )

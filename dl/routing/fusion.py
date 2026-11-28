"""
Observation fusion engine for DisasterLens.

Manages multi-observation ingestion, temporal sequencing, conflict resolution,
blocked-to-clear recovery gates, and route alert generation.
Independent of FastAPI and database engines.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dl.contracts.observation import (
    AffectedSegments,
    RoadStatus,
    RouteAlert,
    RouteAlerts,
    SegmentObservation,
)
from dl.routing.freshness import (
    EffectiveRoadStatus,
    compute_effective_status,
    normalize_datetime,
)


class ObservationFusionEngine:
    """
    In-memory fusion service managing segment observation histories and effective statuses.
    """

    def __init__(self) -> None:
        # segment_id -> ordered list of SegmentObservation
        self._history: dict[str, list[SegmentObservation]] = {}

    def get_history(self, segment_id: str) -> list[SegmentObservation]:
        """Returns complete historical record of observations for a segment, ordered by captured_at."""
        return list(self._history.get(segment_id, []))

    def get_all_histories(self) -> dict[str, list[SegmentObservation]]:
        """Returns complete observation history for all segments."""
        return {seg_id: list(obs_list) for seg_id, obs_list in self._history.items()}

    def _resolve_segment_verdict(
        self,
        history: list[SegmentObservation],
    ) -> tuple[RoadStatus | None, datetime | None, bool, SegmentObservation | None]:
        """
        Processes temporal history in ascending captured_at order to resolve current verdict.

        Returns:
            Tuple of (resolved_verdict, latest_captured_at, is_stale_from_blocked, latest_obs)
        """
        if not history:
            return None, None, False, None

        # Sort history strictly by captured_at ascending
        sorted_history = sorted(history, key=lambda o: normalize_datetime(o.captured_at))

        current_verdict: RoadStatus | None = None
        was_ever_blocked = False
        last_obs: SegmentObservation | None = None

        i = 0
        n = len(sorted_history)
        while i < n:
            obs = sorted_history[i]
            last_obs = obs

            # Check for multiple observations with exact same captured_at timestamp
            same_timestamp_obs = [obs]
            while i + 1 < n and normalize_datetime(sorted_history[i + 1].captured_at) == normalize_datetime(obs.captured_at):
                i += 1
                same_timestamp_obs.append(sorted_history[i])
                last_obs = sorted_history[i]

            # Candidate verdict resolution for this timestamp
            candidate_verdict: RoadStatus
            candidate_confidence: float = max(o.confidence for o in same_timestamp_obs)
            candidate_visibility: str = "full" if all((o.visibility or "full").lower() == "full" for o in same_timestamp_obs) else "partial"

            # Check for direct vs mapped disagreement within any observation
            has_direct_mapped_conflict = False
            for o in same_timestamp_obs:
                if (
                    o.direct_verdict is not None
                    and o.mapped_verdict is not None
                    and o.direct_verdict != o.mapped_verdict
                ):
                    has_direct_mapped_conflict = True
                    break

            if has_direct_mapped_conflict:
                candidate_verdict = RoadStatus.UNCERTAIN
            elif len(same_timestamp_obs) > 1:
                # Multiple reports at exact same timestamp
                statuses = {o.verdict for o in same_timestamp_obs}
                if RoadStatus.BLOCKED in statuses and RoadStatus.CLEAR in statuses:
                    # Conservative resolution on conflict: UNCERTAIN
                    candidate_verdict = RoadStatus.UNCERTAIN
                elif RoadStatus.BLOCKED in statuses:
                    candidate_verdict = RoadStatus.BLOCKED
                elif RoadStatus.PARTIAL in statuses:
                    candidate_verdict = RoadStatus.PARTIAL
                elif RoadStatus.UNCERTAIN in statuses:
                    candidate_verdict = RoadStatus.UNCERTAIN
                else:
                    candidate_verdict = RoadStatus.CLEAR
            else:
                candidate_verdict = obs.verdict

            # Check transitions and recovery gates
            if current_verdict == RoadStatus.BLOCKED and candidate_verdict == RoadStatus.CLEAR:
                # Recovery gate: requires confidence >= 0.7 and full visibility
                if candidate_confidence >= 0.7 and candidate_visibility.lower() == "full":
                    current_verdict = RoadStatus.CLEAR
                else:
                    # Incomplete evidence for recovery -> UNCERTAIN
                    current_verdict = RoadStatus.UNCERTAIN
            else:
                current_verdict = candidate_verdict

            if current_verdict == RoadStatus.BLOCKED:
                was_ever_blocked = True

            i += 1

        latest_captured_at = sorted_history[-1].captured_at
        return current_verdict, latest_captured_at, was_ever_blocked, last_obs

    def get_effective_state(
        self,
        segment_id: str,
        as_of: datetime,
    ) -> EffectiveRoadStatus:
        """
        Computes effective road condition for a segment evaluated at as_of.
        Considers only observations captured at or before as_of.
        """
        norm_as_of = normalize_datetime(as_of)
        valid_history = [
            o for o in self._history.get(segment_id, [])
            if normalize_datetime(o.captured_at) <= norm_as_of
        ]

        if not valid_history:
            return EffectiveRoadStatus(
                status=RoadStatus.UNKNOWN,
                freshness="unknown",
                age_hours=None,
                is_stale_from_blocked=False,
                original_verdict=None,
                captured_at=None,
            )

        verdict, latest_captured, _was_blocked, _last_obs = self._resolve_segment_verdict(valid_history)

        if verdict is None or latest_captured is None:
            return EffectiveRoadStatus(
                status=RoadStatus.UNKNOWN,
                freshness="unknown",
                age_hours=None,
                is_stale_from_blocked=False,
                original_verdict=None,
                captured_at=None,
            )

        return compute_effective_status(
            verdict=verdict,
            captured_at=latest_captured,
            as_of=as_of,
        )

    def get_all_effective_states(
        self,
        as_of: datetime,
        all_segment_ids: list[str] | None = None,
    ) -> dict[str, EffectiveRoadStatus]:
        """
        Returns a dictionary of effective states for all known segments.
        """
        seg_ids = set(self._history.keys())
        if all_segment_ids:
            seg_ids.update(all_segment_ids)

        return {sid: self.get_effective_state(sid, as_of) for sid in seg_ids}

    def ingest_observation(
        self,
        observation: SegmentObservation,
        as_of: datetime | None = None,
        tracked_routes: list[dict[str, Any]] | None = None,
    ) -> tuple[AffectedSegments, RouteAlerts]:
        """
        Ingests a single segment observation into history, computes status changes,
        and generates route alerts for impacted saved routes.
        """
        return self.ingest_observations_bulk([observation], as_of=as_of, tracked_routes=tracked_routes)

    def ingest_observations_bulk(
        self,
        observations: list[SegmentObservation],
        as_of: datetime | None = None,
        tracked_routes: list[dict[str, Any]] | None = None,
    ) -> tuple[AffectedSegments, RouteAlerts]:
        """
        Ingests a batch of observations (e.g. from a multi-segment camera view),
        updates histories, calculates status deltas, and emits route alerts.
        """
        if not observations:
            return (
                AffectedSegments(observation_id="empty", affected_segment_ids=[], previous_statuses={}, new_statuses={}),
                RouteAlerts(alerts=[]),
            )

        if as_of is not None:
            eval_as_of = as_of
        else:
            all_caps = [normalize_datetime(o.captured_at) for o in observations]
            for h in self._history.values():
                all_caps.extend(normalize_datetime(o.captured_at) for o in h)
            eval_as_of = max(all_caps) if all_caps else datetime.now(UTC)

        # 1. Snapshot previous effective statuses for segments touched by this batch
        touched_segments = list({o.segment_id for o in observations})
        prev_statuses: dict[str, RoadStatus] = {}
        for sid in touched_segments:
            prev_statuses[sid] = self.get_effective_state(sid, eval_as_of).status

        # 2. Append observations to history
        for obs in observations:
            if obs.segment_id not in self._history:
                self._history[obs.segment_id] = []
            self._history[obs.segment_id].append(obs)

        # 3. Compute new effective statuses
        new_statuses: dict[str, RoadStatus] = {}
        changed_segment_ids: list[str] = []
        for sid in touched_segments:
            new_st = self.get_effective_state(sid, eval_as_of).status
            new_statuses[sid] = new_st
            if new_st != prev_statuses[sid]:
                changed_segment_ids.append(sid)

        primary_obs_id = observations[0].observation_id
        affected = AffectedSegments(
            observation_id=primary_obs_id,
            affected_segment_ids=changed_segment_ids,
            previous_statuses=prev_statuses,
            new_statuses=new_statuses,
        )

        # 4. Generate route alerts for tracked routes
        alerts_list: list[RouteAlert] = []
        if tracked_routes and changed_segment_ids:
            for route_info in tracked_routes:
                route_id = route_info.get("route_id", "saved_route")
                segment_path = route_info.get("segment_path", [])

                for sid in changed_segment_ids:
                    if sid in segment_path:
                        old_s = prev_statuses.get(sid, RoadStatus.UNKNOWN)
                        new_s = new_statuses.get(sid, RoadStatus.UNKNOWN)

                        if new_s == RoadStatus.BLOCKED:
                            alerts_list.append(
                                RouteAlert(
                                    route_id=route_id,
                                    alert_type="PRIMARY_NOW_BLOCKED",
                                    segment_id=sid,
                                    message=f"Primary route is now blocked by confirmed hazard on {sid}.",
                                    severity="critical",
                                )
                            )
                        elif old_s in (RoadStatus.BLOCKED, RoadStatus.UNCERTAIN) and new_s == RoadStatus.CLEAR:
                            alerts_list.append(
                                RouteAlert(
                                    route_id=route_id,
                                    alert_type="ROUTE_CLEARED",
                                    segment_id=sid,
                                    message=f"Hazard on segment {sid} has receded; corridor status confirmed clear.",
                                    severity="info",
                                )
                            )
                        elif (old_s == RoadStatus.BLOCKED and new_s == RoadStatus.UNCERTAIN) or new_s in (RoadStatus.UNCERTAIN, RoadStatus.STALE, RoadStatus.UNKNOWN):
                            alerts_list.append(
                                RouteAlert(
                                    route_id=route_id,
                                    alert_type="ROUTE_DEGRADED",
                                    segment_id=sid,
                                    message=f"Segment {sid} condition degraded to {new_s.value}.",
                                    severity="warning",
                                )
                            )

        return affected, RouteAlerts(alerts=alerts_list)

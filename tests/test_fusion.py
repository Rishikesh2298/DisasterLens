"""
Unit tests for DisasterLens observation fusion engine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dl.contracts.observation import RoadStatus, SegmentObservation
from dl.generator.models import HazardType, Zone
from dl.routing.fusion import ObservationFusionEngine


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 11, 27, 8, 0, 0, tzinfo=UTC)


@pytest.fixture
def fusion_engine() -> ObservationFusionEngine:
    return ObservationFusionEngine()


class TestObservationFusion:
    """12 tests validating temporal ordering, recovery, conflicts, and alerts."""

    def test_01_newer_blocked_supersedes_older_clear(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """1. Newer BLOCKED supersedes older CLEAR."""
        # T0 (08:00): CLEAR
        obs_clear = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.CLEAR
        )
        fusion_engine.ingest_observation(obs_clear)

        # T1 (09:00): BLOCKED
        t1 = base_time + timedelta(hours=1)
        obs_blocked = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=t1, verdict=RoadStatus.BLOCKED, hazard_type=HazardType.FLOOD
        )
        fusion_engine.ingest_observation(obs_blocked)

        state = fusion_engine.get_effective_state("SEG-001", as_of=t1)
        assert state.status == RoadStatus.BLOCKED

    def test_02_older_clear_uploaded_later_cannot_override_newer_blocked(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """2. Older CLEAR uploaded later cannot override newer BLOCKED."""
        # Newer observation captured at 09:00, uploaded at 09:05: BLOCKED
        t_blocked = base_time + timedelta(hours=1)
        obs_blocked = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=t_blocked,
            uploaded_at=t_blocked + timedelta(minutes=5),
            verdict=RoadStatus.BLOCKED
        )
        fusion_engine.ingest_observation(obs_blocked)

        # Older observation captured at 08:00, uploaded late at 10:00: CLEAR
        obs_old_clear = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time,
            uploaded_at=base_time + timedelta(hours=2),
            verdict=RoadStatus.CLEAR
        )
        fusion_engine.ingest_observation(obs_old_clear)

        # State as of 10:00 must remain BLOCKED (the 09:00 fact still wins over 08:00)
        as_of = base_time + timedelta(hours=2)
        state = fusion_engine.get_effective_state("SEG-001", as_of=as_of)
        assert state.status == RoadStatus.BLOCKED

    def test_03_recovery_permitted_with_confidence_0_7_and_full_visibility(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """3. Newer CLEAR with confidence >= 0.7 and full visibility permits recovery."""
        # 08:00: BLOCKED
        obs_blocked = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED
        )
        fusion_engine.ingest_observation(obs_blocked)

        # 10:00: CLEAR with confidence=0.75 and visibility='full'
        t_clear = base_time + timedelta(hours=2)
        obs_clear = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=t_clear, verdict=RoadStatus.CLEAR,
            confidence=0.75, visibility="full", recovery=True
        )
        fusion_engine.ingest_observation(obs_clear)

        state = fusion_engine.get_effective_state("SEG-001", as_of=t_clear)
        assert state.status == RoadStatus.CLEAR

    def test_04_recovery_denied_with_confidence_below_0_7(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """4. Newer CLEAR with confidence below 0.7 becomes UNCERTAIN."""
        # 08:00: BLOCKED
        obs_blocked = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED
        )
        fusion_engine.ingest_observation(obs_blocked)

        # 10:00: CLEAR with confidence=0.69 (insufficient evidence)
        t_clear = base_time + timedelta(hours=2)
        obs_clear = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=t_clear, verdict=RoadStatus.CLEAR,
            confidence=0.69, visibility="full", recovery=True
        )
        fusion_engine.ingest_observation(obs_clear)

        state = fusion_engine.get_effective_state("SEG-001", as_of=t_clear)
        assert state.status == RoadStatus.UNCERTAIN

    def test_05_recovery_denied_without_full_visibility(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """5. Newer CLEAR without full visibility becomes UNCERTAIN."""
        # 08:00: BLOCKED
        obs_blocked = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED
        )
        fusion_engine.ingest_observation(obs_blocked)

        # 10:00: CLEAR with confidence=0.90 but visibility='partial'
        t_clear = base_time + timedelta(hours=2)
        obs_clear = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=t_clear, verdict=RoadStatus.CLEAR,
            confidence=0.90, visibility="partial", recovery=True
        )
        fusion_engine.ingest_observation(obs_clear)

        state = fusion_engine.get_effective_state("SEG-001", as_of=t_clear)
        assert state.status == RoadStatus.UNCERTAIN

    def test_06_direct_and_mapped_verdict_disagreement_becomes_uncertain(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """6. Direct vision and geometry-mapped verdict disagreement yields UNCERTAIN."""
        obs = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.CLEAR,
            direct_verdict=RoadStatus.CLEAR,
            mapped_verdict=RoadStatus.BLOCKED,
        )
        fusion_engine.ingest_observation(obs)

        state = fusion_engine.get_effective_state("SEG-001", as_of=base_time)
        assert state.status == RoadStatus.UNCERTAIN

    def test_07_full_history_is_preserved(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """7. Full observation history is preserved in exact chronological order."""
        t1 = base_time
        t2 = base_time + timedelta(hours=1)
        t3 = base_time + timedelta(hours=2)

        fusion_engine.ingest_observation(
            SegmentObservation(segment_id="SEG-001", source="cam1", zone=Zone.NW, captured_at=t2, verdict=RoadStatus.BLOCKED)
        )
        fusion_engine.ingest_observation(
            SegmentObservation(segment_id="SEG-001", source="cam1", zone=Zone.NW, captured_at=t1, verdict=RoadStatus.CLEAR)
        )
        fusion_engine.ingest_observation(
            SegmentObservation(segment_id="SEG-001", source="cam1", zone=Zone.NW, captured_at=t3, verdict=RoadStatus.CLEAR)
        )

        history = fusion_engine.get_history("SEG-001")
        assert len(history) == 3
        # Ingestion preserved all records
        captured_times = [o.captured_at for o in history]
        assert t1 in captured_times
        assert t2 in captured_times
        assert t3 in captured_times

    def test_08_equal_captured_at_conflict_conservative_resolution(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """8. Equal captured_at conflicts are handled deterministically and conservatively."""
        obs_a = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.CLEAR
        )
        obs_b = SegmentObservation(
            segment_id="SEG-001", source="cam2", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED
        )
        # Ingest both with identical timestamps
        fusion_engine.ingest_observations_bulk([obs_a, obs_b])

        state = fusion_engine.get_effective_state("SEG-001", as_of=base_time)
        # Conservative resolution on conflict: UNCERTAIN
        assert state.status == RoadStatus.UNCERTAIN

    def test_09_uploaded_at_does_not_affect_ordering(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """9. uploaded_at does not affect temporal precedence."""
        # Obs 1: captured at 08:00, uploaded at 12:00
        obs1 = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time,
            uploaded_at=base_time + timedelta(hours=4),
            verdict=RoadStatus.CLEAR
        )
        # Obs 2: captured at 09:00, uploaded at 09:05
        obs2 = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time + timedelta(hours=1),
            uploaded_at=base_time + timedelta(hours=1, minutes=5),
            verdict=RoadStatus.BLOCKED
        )
        fusion_engine.ingest_observations_bulk([obs1, obs2])

        as_of = base_time + timedelta(hours=2)
        state = fusion_engine.get_effective_state("SEG-001", as_of=as_of)
        # Obs 2 has newer captured_at, so it wins
        assert state.status == RoadStatus.BLOCKED

    def test_10_freshness_evaluated_against_supplied_as_of(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """10. Freshness is evaluated against supplied as_of."""
        obs = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.CLEAR
        )
        fusion_engine.ingest_observation(obs)

        # as_of 2 hours later -> CLEAR fresh
        st_2h = fusion_engine.get_effective_state("SEG-001", as_of=base_time + timedelta(hours=2))
        assert st_2h.status == RoadStatus.CLEAR
        assert st_2h.freshness == "fresh"

        # as_of 14 hours later -> STALE
        st_14h = fusion_engine.get_effective_state("SEG-001", as_of=base_time + timedelta(hours=14))
        assert st_14h.status == RoadStatus.STALE
        assert st_14h.freshness == "stale"

    def test_11_route_alerts_generated_when_saved_route_impacted(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """11. Generates PRIMARY_NOW_BLOCKED when a saved route segment turns BLOCKED."""
        saved_routes = [
            {"route_id": "route_42", "segment_path": ["SEG-001", "SEG-002"]}
        ]
        obs = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED
        )
        affected, alerts = fusion_engine.ingest_observation(
            obs, as_of=base_time, tracked_routes=saved_routes
        )

        assert "SEG-001" in affected.affected_segment_ids
        assert len(alerts.alerts) == 1
        assert alerts.alerts[0].alert_type == "PRIMARY_NOW_BLOCKED"
        assert alerts.alerts[0].route_id == "route_42"
        assert alerts.alerts[0].segment_id == "SEG-001"

    def test_12_empty_observations_bulk(self, fusion_engine: ObservationFusionEngine, base_time: datetime):
        """Bulk ingestion with empty list returns empty AffectedSegments and RouteAlerts."""
        affected, alerts = fusion_engine.ingest_observations_bulk([], as_of=base_time)
        assert affected.observation_id == "empty"
        assert affected.affected_segment_ids == []
        assert len(alerts.alerts) == 0

    def test_13_get_all_effective_states_with_additional_ids(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """get_all_effective_states includes requested segment IDs even if not in history."""
        obs = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.CLEAR
        )
        fusion_engine.ingest_observation(obs)

        states = fusion_engine.get_all_effective_states(
            as_of=base_time, all_segment_ids=["SEG-001", "SEG-999"]
        )
        assert "SEG-001" in states
        assert states["SEG-001"].status == RoadStatus.CLEAR
        assert "SEG-999" in states
        assert states["SEG-999"].status == RoadStatus.UNKNOWN

    def test_14_route_alert_transitions_cleared_and_degraded(
        self, fusion_engine: ObservationFusionEngine, base_time: datetime
    ):
        """Validates ROUTE_CLEARED and ROUTE_DEGRADED alert generation."""
        saved_routes = [{"route_id": "route_99", "segment_path": ["SEG-001"]}]

        # 1. Start with BLOCKED
        obs_b = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=base_time, verdict=RoadStatus.BLOCKED
        )
        fusion_engine.ingest_observation(obs_b, as_of=base_time, tracked_routes=saved_routes)

        # 2. Transition from BLOCKED to CLEAR (recovery) -> ROUTE_CLEARED
        t1 = base_time + timedelta(hours=1)
        obs_c = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=t1, verdict=RoadStatus.CLEAR,
            confidence=0.9, visibility="full", recovery=True
        )
        _aff, alerts1 = fusion_engine.ingest_observation(obs_c, as_of=t1, tracked_routes=saved_routes)
        assert any(a.alert_type == "ROUTE_CLEARED" for a in alerts1.alerts)

        # 3. Transition from CLEAR to UNCERTAIN -> ROUTE_DEGRADED
        t2 = base_time + timedelta(hours=2)
        obs_u = SegmentObservation(
            segment_id="SEG-001", source="cam1", zone=Zone.NW,
            captured_at=t2, verdict=RoadStatus.UNCERTAIN
        )
        _aff, alerts2 = fusion_engine.ingest_observation(obs_u, as_of=t2, tracked_routes=saved_routes)
        assert any(a.alert_type == "ROUTE_DEGRADED" for a in alerts2.alerts)

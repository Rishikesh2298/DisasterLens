"""
Unit and table-driven tests for freshness, decay thresholds, and edge costs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from dl.contracts.observation import RoadStatus
from dl.routing.costs import compute_edge_cost, get_cost_multiplier
from dl.routing.freshness import (
    compute_effective_status,
)


@pytest.fixture
def base_as_of() -> datetime:
    """Fixed reference query time: 2026-11-27 12:00:00+05:30 (IST)."""
    return datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


class TestFreshnessThresholds:
    """Tests 6–16: Precise boundary evaluations and decay rules."""

    def test_06_clear_at_exactly_3_hours(self, base_as_of: datetime):
        """Requirement 6: CLEAR at exactly 3.0 hours is 'fresh' (multiplier 1.0)."""
        captured_at = base_as_of - timedelta(hours=3)
        res = compute_effective_status(RoadStatus.CLEAR, captured_at, as_of=base_as_of)

        assert res.status == RoadStatus.CLEAR
        assert res.freshness == "fresh"
        assert abs(res.age_hours - 3.0) < 1e-5
        assert get_cost_multiplier(res.status, res.freshness) == 1.0

    def test_07_clear_just_above_3_hours(self, base_as_of: datetime):
        """Requirement 7: CLEAR just above 3 hours (3h + 1s) is 'ageing' (multiplier 1.5)."""
        captured_at = base_as_of - timedelta(hours=3, seconds=1)
        res = compute_effective_status(RoadStatus.CLEAR, captured_at, as_of=base_as_of)

        assert res.status == RoadStatus.CLEAR
        assert res.freshness == "ageing"
        assert res.age_hours > 3.0
        assert get_cost_multiplier(res.status, res.freshness) == 1.5

    def test_08_clear_at_exactly_12_hours(self, base_as_of: datetime):
        """Requirement 8: CLEAR at exactly 12.0 hours is 'ageing' (multiplier 1.5)."""
        captured_at = base_as_of - timedelta(hours=12)
        res = compute_effective_status(RoadStatus.CLEAR, captured_at, as_of=base_as_of)

        assert res.status == RoadStatus.CLEAR
        assert res.freshness == "ageing"
        assert abs(res.age_hours - 12.0) < 1e-5
        assert get_cost_multiplier(res.status, res.freshness) == 1.5

    def test_09_clear_just_above_12_hours(self, base_as_of: datetime):
        """Requirement 9: CLEAR just above 12 hours (12h + 1s) is 'STALE' (multiplier 3.0)."""
        captured_at = base_as_of - timedelta(hours=12, seconds=1)
        res = compute_effective_status(RoadStatus.CLEAR, captured_at, as_of=base_as_of)

        assert res.status == RoadStatus.STALE
        assert res.freshness == "stale"
        assert res.is_stale_from_blocked is False
        assert res.age_hours > 12.0
        assert get_cost_multiplier(res.status, res.freshness) == 3.0

    def test_10_blocked_at_exactly_24_hours(self, base_as_of: datetime):
        """Requirement 10: BLOCKED at exactly 24.0 hours remains BLOCKED (excluded from routing)."""
        captured_at = base_as_of - timedelta(hours=24)
        res = compute_effective_status(RoadStatus.BLOCKED, captured_at, as_of=base_as_of)

        assert res.status == RoadStatus.BLOCKED
        assert res.freshness == "fresh"
        assert abs(res.age_hours - 24.0) < 1e-5
        assert get_cost_multiplier(res.status, res.freshness) is None  # Excluded

    def test_11_blocked_just_above_24_hours_remains_avoided(self, base_as_of: datetime):
        """Requirement 11: BLOCKED older than 24 hours becomes STALE but retains 8.0 penalty."""
        captured_at = base_as_of - timedelta(hours=24, seconds=1)
        res = compute_effective_status(RoadStatus.BLOCKED, captured_at, as_of=base_as_of)

        assert res.status == RoadStatus.STALE
        assert res.freshness == "stale"
        assert res.is_stale_from_blocked is True
        # Must return 8.0 multiplier to remain heavily avoided
        mult = get_cost_multiplier(res.status, res.freshness, is_stale_from_blocked=res.is_stale_from_blocked)
        assert mult == 8.0
        cost = compute_edge_cost(100.0, res.status, res.freshness, is_stale_from_blocked=True)
        assert cost == 800.0

    def test_12_partial_at_12_hours_and_just_above(self, base_as_of: datetime):
        """Requirement 12: PARTIAL at 12 hours is PARTIAL; older becomes STALE."""
        # Exactly 12 hours -> PARTIAL (fresh)
        cap_12h = base_as_of - timedelta(hours=12)
        res_12h = compute_effective_status(RoadStatus.PARTIAL, cap_12h, as_of=base_as_of)
        assert res_12h.status == RoadStatus.PARTIAL
        assert res_12h.freshness == "fresh"
        assert get_cost_multiplier(res_12h.status, res_12h.freshness) == 1.5

        # Just above 12 hours -> STALE
        cap_12h_1s = base_as_of - timedelta(hours=12, seconds=1)
        res_older = compute_effective_status(RoadStatus.PARTIAL, cap_12h_1s, as_of=base_as_of)
        assert res_older.status == RoadStatus.STALE
        assert res_older.freshness == "stale"
        assert res_older.is_stale_from_blocked is False
        assert get_cost_multiplier(res_older.status, res_older.freshness) == 3.0

    def test_13_uncertain_at_12_hours_and_just_above(self, base_as_of: datetime):
        """Requirement 13: UNCERTAIN at 12 hours is UNCERTAIN (x4.0); older becomes UNKNOWN (x3.0)."""
        # Exactly 12 hours -> UNCERTAIN
        cap_12h = base_as_of - timedelta(hours=12)
        res_12h = compute_effective_status(RoadStatus.UNCERTAIN, cap_12h, as_of=base_as_of)
        assert res_12h.status == RoadStatus.UNCERTAIN
        assert res_12h.freshness == "fresh"
        assert get_cost_multiplier(res_12h.status, res_12h.freshness) == 4.0

        # Just above 12 hours -> UNKNOWN
        cap_12h_1s = base_as_of - timedelta(hours=12, seconds=1)
        res_older = compute_effective_status(RoadStatus.UNCERTAIN, cap_12h_1s, as_of=base_as_of)
        assert res_older.status == RoadStatus.UNKNOWN
        assert res_older.freshness == "unknown"
        assert get_cost_multiplier(res_older.status, res_older.freshness) == 3.0

    def test_14_no_observation_returns_unknown(self, base_as_of: datetime):
        """Requirement 14: No observation returns UNKNOWN with unknown freshness."""
        res = compute_effective_status(None, None, as_of=base_as_of)
        assert res.status == RoadStatus.UNKNOWN
        assert res.freshness == "unknown"
        assert res.age_hours is None
        assert get_cost_multiplier(res.status, res.freshness) == 3.0

    def test_15_changing_uploaded_at_does_not_affect_freshness(self, base_as_of: datetime):
        """Requirement 15: Changing uploaded_at without changing captured_at does not change freshness."""
        captured_at = base_as_of - timedelta(hours=2)

        # Ingestion 1: uploaded immediately after capture
        upload_time_1 = captured_at + timedelta(minutes=5)
        res_1 = compute_effective_status(
            RoadStatus.CLEAR, captured_at, as_of=base_as_of, uploaded_at=upload_time_1
        )

        # Ingestion 2: delayed upload 10 hours later
        upload_time_2 = captured_at + timedelta(hours=10)
        res_2 = compute_effective_status(
            RoadStatus.CLEAR, captured_at, as_of=base_as_of, uploaded_at=upload_time_2
        )

        assert res_1.status == res_2.status
        assert res_1.freshness == res_2.freshness
        assert res_1.age_hours == res_2.age_hours
        assert res_1.is_stale_from_blocked == res_2.is_stale_from_blocked

    def test_16_simulated_as_of_produces_deterministic_results(self):
        """Requirement 16: Simulated as_of produces exact, repeatable results across clock shifts."""
        captured_at = datetime(2026, 11, 27, 8, 0, 0, tzinfo=UTC)

        # Simulation Step T1: as_of at 09:00 (1 hour old) -> CLEAR fresh
        as_of_t1 = datetime(2026, 11, 27, 9, 0, 0, tzinfo=UTC)
        res_t1 = compute_effective_status(RoadStatus.CLEAR, captured_at, as_of=as_of_t1)
        assert res_t1.status == RoadStatus.CLEAR
        assert res_t1.freshness == "fresh"

        # Simulation Step T2: advance clock to 14:00 (6 hours old) -> CLEAR ageing
        as_of_t2 = datetime(2026, 11, 27, 14, 0, 0, tzinfo=UTC)
        res_t2 = compute_effective_status(RoadStatus.CLEAR, captured_at, as_of=as_of_t2)
        assert res_t2.status == RoadStatus.CLEAR
        assert res_t2.freshness == "ageing"

        # Simulation Step T3: advance clock to 22:00 (14 hours old) -> STALE
        as_of_t3 = datetime(2026, 11, 27, 22, 0, 0, tzinfo=UTC)
        res_t3 = compute_effective_status(RoadStatus.CLEAR, captured_at, as_of=as_of_t3)
        assert res_t3.status == RoadStatus.STALE
        assert res_t3.freshness == "stale"

    def test_future_observation_rejection(self, base_as_of: datetime):
        """Future observation (captured_at > as_of) raises ValueError at boundary."""
        future_captured_at = base_as_of + timedelta(minutes=10)
        with pytest.raises(ValueError, match="is in the future"):
            compute_effective_status(RoadStatus.CLEAR, future_captured_at, as_of=base_as_of)


class TestTableDrivenMultipliers:
    """Table-driven test confirming all status and multiplier combinations."""

    @pytest.mark.parametrize(
        "status,freshness,is_stale_from_blocked,expected_multiplier",
        [
            (RoadStatus.CLEAR, "fresh", False, 1.0),
            (RoadStatus.CLEAR, "ageing", False, 1.5),
            (RoadStatus.CLEAR, "stale", False, 3.0),
            (RoadStatus.PARTIAL, "fresh", False, 1.5),
            (RoadStatus.UNCERTAIN, "fresh", False, 4.0),
            (RoadStatus.UNKNOWN, "unknown", False, 3.0),
            (RoadStatus.STALE, "stale", False, 3.0),
            (RoadStatus.STALE, "stale", True, 8.0),
            (RoadStatus.BLOCKED, "fresh", False, None),
        ],
    )
    def test_multipliers_table(
        self,
        status: RoadStatus,
        freshness: str,
        is_stale_from_blocked: bool,
        expected_multiplier: float | None,
    ):
        actual = get_cost_multiplier(
            status=status,
            freshness=freshness,
            is_stale_from_blocked=is_stale_from_blocked,
        )
        assert actual == expected_multiplier

    def test_17_stale_and_unknown_and_uncertain_decay(self, base_as_of: datetime):
        """Verifies decay handling for STALE, UNKNOWN, and UNCERTAIN."""
        cap = base_as_of - timedelta(hours=1)
        # STALE verdict input
        res_stale = compute_effective_status(RoadStatus.STALE, cap, as_of=base_as_of)
        assert res_stale.status == RoadStatus.STALE
        assert res_stale.freshness == "stale"

        # UNKNOWN verdict input
        res_unk = compute_effective_status(RoadStatus.UNKNOWN, cap, as_of=base_as_of)
        assert res_unk.status == RoadStatus.UNKNOWN
        assert res_unk.freshness == "unknown"

        # UNCERTAIN: fresh within 12h, unknown after 12h
        res_unc_fresh = compute_effective_status(RoadStatus.UNCERTAIN, base_as_of - timedelta(hours=3), as_of=base_as_of)
        assert res_unc_fresh.status == RoadStatus.UNCERTAIN
        assert res_unc_fresh.freshness == "fresh"

        res_unc_old = compute_effective_status(RoadStatus.UNCERTAIN, base_as_of - timedelta(hours=13), as_of=base_as_of)
        assert res_unc_old.status == RoadStatus.UNKNOWN
        assert res_unc_old.freshness == "unknown"

    def test_18_costs_functions_direct(self):
        """Directly tests compute_edge_cost and compute_edge_cost_from_effective."""
        from dl.routing.costs import compute_edge_cost, compute_edge_cost_from_effective
        from dl.routing.freshness import EffectiveRoadStatus

        # Blocked returns None
        assert compute_edge_cost(100.0, RoadStatus.BLOCKED) is None

        # Effective status
        eff_clear = EffectiveRoadStatus(status=RoadStatus.CLEAR, freshness="fresh", age_hours=1.0)
        assert compute_edge_cost_from_effective(50.0, eff_clear) == 50.0

        eff_blocked = EffectiveRoadStatus(status=RoadStatus.BLOCKED, freshness="fresh", age_hours=1.0)
        assert compute_edge_cost_from_effective(50.0, eff_blocked) is None

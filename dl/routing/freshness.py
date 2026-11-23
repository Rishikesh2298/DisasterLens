"""
Freshness and effective status engine for DisasterLens.

Calculates road segment condition at query time (as_of) strictly using
captured_at timestamps and YAML-configured decay thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from dl.contracts.scene import RoadStatus

# Default freshness configuration path
DEFAULT_CONFIG_PATH = Path(__file__).parent / "freshness.yaml"


def load_freshness_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Loads freshness threshold configuration from YAML."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        # Fallback default values matching the shared project rules
        return {
            "thresholds": {
                "clear": {"fresh_max_hours": 3.0, "ageing_max_hours": 12.0, "stale_after_hours": 12.0},
                "blocked": {"active_max_hours": 24.0, "stale_after_hours": 24.0},
                "partial": {"active_max_hours": 12.0, "stale_after_hours": 12.0},
                "uncertain": {"active_max_hours": 12.0, "unknown_after_hours": 12.0},
            }
        }
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class EffectiveRoadStatus:
    """
    Computed road condition evaluated at a specific reference timestamp (as_of).

    Attributes:
        status: Effective status enum (BLOCKED, PARTIAL, CLEAR, UNCERTAIN, STALE, UNKNOWN).
        freshness: Freshness classification ('fresh', 'ageing', 'stale', 'unknown').
        age_hours: Elapsed hours from captured_at to as_of.
        is_stale_from_blocked: True if the segment is STALE originating from a BLOCKED observation.
        original_verdict: Original raw observation verdict.
        captured_at: Timestamp when imagery was captured.
    """

    status: RoadStatus
    freshness: str
    age_hours: float | None
    is_stale_from_blocked: bool = False
    original_verdict: RoadStatus | None = None
    captured_at: datetime | None = None


def normalize_datetime(dt: datetime) -> datetime:
    """Ensures datetime is timezone-aware in UTC."""
    if dt.tzinfo is None:
        # Interpret naive datetime as UTC
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def compute_effective_status(
    verdict: RoadStatus | str | None,
    captured_at: datetime | None,
    as_of: datetime,
    uploaded_at: datetime | None = None,
    config: dict[str, Any] | None = None,
) -> EffectiveRoadStatus:
    """
    Computes the effective condition of a road segment at query time (as_of).

    Rules:
      - Age is calculated strictly using captured_at vs as_of.
      - uploaded_at is ignored and never influences freshness.
      - If captured_at is in the future relative to as_of, raises ValueError.
      - If verdict is None, returns UNKNOWN.

    CLEAR:
      - 0 to 3 hours: fresh
      - >3 to 12 hours: ageing
      - >12 hours: STALE

    BLOCKED:
      - 0 to 24 hours: BLOCKED (fresh)
      - >24 hours: STALE, but remains avoided by routing (is_stale_from_blocked=True)

    PARTIAL:
      - 0 to 12 hours: PARTIAL
      - >12 hours: STALE

    UNCERTAIN:
      - 0 to 12 hours: UNCERTAIN
      - >12 hours: UNKNOWN

    No observation:
      - UNKNOWN
    """
    if verdict is None or captured_at is None:
        return EffectiveRoadStatus(
            status=RoadStatus.UNKNOWN,
            freshness="unknown",
            age_hours=None,
            is_stale_from_blocked=False,
            original_verdict=None,
            captured_at=None,
        )

    norm_captured = normalize_datetime(captured_at)
    norm_as_of = normalize_datetime(as_of)

    time_delta = norm_as_of - norm_captured
    age_seconds = time_delta.total_seconds()

    if age_seconds < 0:
        raise ValueError(
            f"Observation captured_at ({captured_at.isoformat()}) is in the future "
            f"relative to reference as_of ({as_of.isoformat()})."
        )

    age_hours = age_seconds / 3600.0

    # Ensure verdict is a RoadStatus enum
    if isinstance(verdict, str):
        verdict = RoadStatus(verdict)

    cfg = config or load_freshness_config()
    thresholds = cfg.get("thresholds", {})

    # Evaluate based on original verdict
    if verdict == RoadStatus.CLEAR:
        clear_cfg = thresholds.get("clear", {})
        fresh_max = clear_cfg.get("fresh_max_hours", 3.0)
        ageing_max = clear_cfg.get("ageing_max_hours", 12.0)

        if age_hours <= fresh_max:
            return EffectiveRoadStatus(
                status=RoadStatus.CLEAR,
                freshness="fresh",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )
        elif age_hours <= ageing_max:
            return EffectiveRoadStatus(
                status=RoadStatus.CLEAR,
                freshness="ageing",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )
        else:
            return EffectiveRoadStatus(
                status=RoadStatus.STALE,
                freshness="stale",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )

    elif verdict == RoadStatus.BLOCKED:
        blocked_cfg = thresholds.get("blocked", {})
        active_max = blocked_cfg.get("active_max_hours", 24.0)

        if age_hours <= active_max:
            return EffectiveRoadStatus(
                status=RoadStatus.BLOCKED,
                freshness="fresh",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )
        else:
            # Over 24 hours: STALE, but still avoided by routing
            return EffectiveRoadStatus(
                status=RoadStatus.STALE,
                freshness="stale",
                age_hours=age_hours,
                is_stale_from_blocked=True,
                original_verdict=verdict,
                captured_at=captured_at,
            )

    elif verdict == RoadStatus.PARTIAL:
        partial_cfg = thresholds.get("partial", {})
        active_max = partial_cfg.get("active_max_hours", 12.0)

        if age_hours <= active_max:
            return EffectiveRoadStatus(
                status=RoadStatus.PARTIAL,
                freshness="fresh",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )
        else:
            return EffectiveRoadStatus(
                status=RoadStatus.STALE,
                freshness="stale",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )

    elif verdict == RoadStatus.UNCERTAIN:
        unc_cfg = thresholds.get("uncertain", {})
        active_max = unc_cfg.get("active_max_hours", 12.0)

        if age_hours <= active_max:
            return EffectiveRoadStatus(
                status=RoadStatus.UNCERTAIN,
                freshness="fresh",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )
        else:
            return EffectiveRoadStatus(
                status=RoadStatus.UNKNOWN,
                freshness="unknown",
                age_hours=age_hours,
                is_stale_from_blocked=False,
                original_verdict=verdict,
                captured_at=captured_at,
            )

    elif verdict == RoadStatus.STALE:
        return EffectiveRoadStatus(
            status=RoadStatus.STALE,
            freshness="stale",
            age_hours=age_hours,
            is_stale_from_blocked=False,
            original_verdict=verdict,
            captured_at=captured_at,
        )

    else:  # UNKNOWN or unrecognized
        return EffectiveRoadStatus(
            status=RoadStatus.UNKNOWN,
            freshness="unknown",
            age_hours=age_hours,
            is_stale_from_blocked=False,
            original_verdict=verdict,
            captured_at=captured_at,
        )

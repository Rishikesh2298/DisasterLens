"""
Clock service providing deterministic simulated time management.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dl.routing.freshness import normalize_datetime


class ClockService:
    """
    Manages deterministic simulated clock time for the DisasterLens platform.
    Ensures simulated time is never silently substituted by wall-clock time.
    """

    def __init__(self) -> None:
        self._simulated_time: datetime | None = None

    def get_simulated_time(self) -> datetime | None:
        """Returns the currently configured simulated time, or None if in wall-clock mode."""
        return self._simulated_time

    def set_simulated_time(self, dt: datetime | None) -> None:
        """Sets or resets the simulated time."""
        if dt is not None:
            self._simulated_time = normalize_datetime(dt)
        else:
            self._simulated_time = None

    def resolve_as_of(self, requested_as_of: datetime | None = None) -> datetime:
        """
        Determines the effective evaluation timestamp:
        1. Explicitly requested query/payload as_of (highest precedence)
        2. Configured simulated time
        3. Real wall-clock UTC time (fallback only when neither 1 nor 2 is present)
        """
        if requested_as_of is not None:
            return normalize_datetime(requested_as_of)
        if self._simulated_time is not None:
            return self._simulated_time
        return datetime.now(UTC)


# Application-level singleton
global_clock = ClockService()

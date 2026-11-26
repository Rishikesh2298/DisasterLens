"""
Simulated clock router managing platform-wide reference time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from dl.api.dependencies import get_clock_service
from dl.api.services.clock_service import ClockService

router = APIRouter(prefix="/clock", tags=["clock"])


class SetClockRequest(BaseModel):
    simulated_time: datetime | None = Field(
        None,
        description="Target simulated timestamp (ISO-8601 UTC). Omit or set null to reset to wall-clock time.",
    )


@router.get("")
def get_clock(
    clock: ClockService = Depends(get_clock_service),
) -> dict[str, Any]:
    """
    Returns the current reference time and active clock mode.
    """
    sim_time = clock.get_simulated_time()
    wall_clock = datetime.now(UTC)
    return {
        "clock_mode": "simulated" if sim_time else "wall-clock",
        "reference_time": (sim_time or wall_clock).isoformat(),
        "simulated_time": sim_time.isoformat() if sim_time else None,
        "wall_clock_time": wall_clock.isoformat(),
    }


@router.post("")
def set_clock(
    req: SetClockRequest,
    clock: ClockService = Depends(get_clock_service),
) -> dict[str, Any]:
    """
    Sets deterministic simulated time, or resets to wall-clock time if null.
    """
    clock.set_simulated_time(req.simulated_time)
    sim_time = clock.get_simulated_time()
    return {
        "status": "updated",
        "clock_mode": "simulated" if sim_time else "wall-clock",
        "simulated_time": sim_time.isoformat() if sim_time else None,
    }

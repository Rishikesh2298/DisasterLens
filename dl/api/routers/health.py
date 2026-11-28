"""
Health check router for DisasterLens backend.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from dl.api.config import settings
from dl.api.dependencies import get_clock_service, get_db_session
from dl.api.services.clock_service import ClockService

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(
    db: Session = Depends(get_db_session),
    clock: ClockService = Depends(get_clock_service),
) -> dict[str, Any]:
    """
    Returns API health status, database connectivity, and active vision mode.
    """
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {e!s}"

    sim_time = clock.get_simulated_time()

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "vision_mode": settings.VISION_MODE,
        "vision_provider": settings.VISION_PROVIDER,
        "simulated_time": sim_time.isoformat() if sim_time else None,
        "clock_mode": "simulated" if sim_time else "wall-clock",
        "disclaimer": (
            "DisasterLens research prototype — conditions may change rapidly. "
            "Results are based on synthetic evaluation scenes and do not establish real-world disaster safety."
        ),
    }

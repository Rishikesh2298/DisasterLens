"""
Scenario router providing demo scenario listings and timeline advancement.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dl.api.dependencies import get_scenario_service
from dl.api.services.scenario_service import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


class AdvanceScenarioRequest(BaseModel):
    time_step: str | None = Field(None, description="Target time step to advance to (e.g. 'T1', 'T2', 'T3')")


@router.get("")
def list_scenarios(
    scenario_service: ScenarioService = Depends(get_scenario_service),
) -> list[dict[str, Any]]:
    """Lists all available demo scenarios."""
    scenarios = scenario_service.list_scenarios()
    return [
        {
            "id": s.id,
            "city_id": s.city_id,
            "description": s.description,
            "current_time_step": s.current_time_step,
            "current_simulated_time": s.current_simulated_time.isoformat() if s.current_simulated_time else None,
        }
        for s in scenarios
    ]


@router.get("/{scenario_id}")
def get_scenario_details(
    scenario_id: str,
    scenario_service: ScenarioService = Depends(get_scenario_service),
) -> dict[str, Any]:
    """Retrieves scenario details, camera setup, and timeline events."""
    s = scenario_service.get_scenario(scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")

    events_data = []
    for ev in s.events:
        obs = json.loads(ev.observations_json) if ev.observations_json else []
        events_data.append({
            "time_step": ev.time_step,
            "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
            "description": ev.description,
            "observations_count": len(obs),
        })

    cameras = json.loads(s.cameras_json) if s.cameras_json else []

    return {
        "id": s.id,
        "city_id": s.city_id,
        "description": s.description,
        "current_time_step": s.current_time_step,
        "current_simulated_time": s.current_simulated_time.isoformat() if s.current_simulated_time else None,
        "cameras": cameras,
        "timeline_events": events_data,
    }


@router.post("/{scenario_id}/advance")
def advance_scenario(
    scenario_id: str,
    req: AdvanceScenarioRequest | None = None,
    scenario_service: ScenarioService = Depends(get_scenario_service),
) -> dict[str, Any]:
    """
    Advances scenario timeline (T0 -> T1 -> T2 -> T3).
    Ingests timeline observations, advances simulated clock, and returns status deltas and route alerts.
    """
    target_step = req.time_step if req else None
    try:
        result = scenario_service.advance_scenario(scenario_id, target_time_step=target_step)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scenario advancement error: {e!s}")

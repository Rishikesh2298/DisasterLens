"""
Scenario service managing demo scenario execution and timeline advancement.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from sqlalchemy.orm import Session

from dl.api.models import Scenario as ScenarioModel
from dl.api.repositories.scenario_repo import ScenarioRepository
from dl.api.services.clock_service import ClockService
from dl.api.services.observation_service import ObservationService
from dl.contracts.observation import SegmentObservation
from dl.vision.provider import VisionProvider, get_vision_provider


class ScenarioService:
    """
    Coordinates scenario timelines, event triggers, and automated observation feeding.
    """

    STEP_SEQUENCE: ClassVar[list[str]] = ["T0", "T1", "T2", "T3"]

    def __init__(
        self,
        db: Session,
        observation_service: ObservationService,
        clock_service: ClockService,
        vision_provider: VisionProvider | None = None,
    ) -> None:
        self.db = db
        self.repo = ScenarioRepository(db)
        self.obs_service = observation_service
        self.clock = clock_service
        self.vision = vision_provider or get_vision_provider("mock")

    def list_scenarios(self) -> list[ScenarioModel]:
        return self.repo.list_scenarios()

    def get_scenario(self, scenario_id: str) -> ScenarioModel | None:
        return self.repo.get_scenario(scenario_id)

    def advance_scenario(
        self,
        scenario_id: str,
        target_time_step: str | None = None,
    ) -> dict[str, Any]:
        """
        Advances a scenario's timeline, ingests timeline observations in correct order,
        synchronizes simulated clock time, and returns delta states and emitted alerts.
        """
        scenario = self.repo.get_scenario(scenario_id)
        if not scenario:
            raise ValueError(f"Scenario '{scenario_id}' not found.")

        current_step = scenario.current_time_step or "T0"

        # Determine target step
        if target_time_step:
            next_step = target_time_step.strip().upper()
        else:
            try:
                curr_idx = self.STEP_SEQUENCE.index(current_step)
                if curr_idx + 1 < len(self.STEP_SEQUENCE):
                    next_step = self.STEP_SEQUENCE[curr_idx + 1]
                else:
                    next_step = current_step
            except ValueError:
                next_step = "T0"

        event = self.repo.get_event_by_step(scenario_id, next_step)
        if not event:
            raise ValueError(f"Event for time step '{next_step}' not found in scenario '{scenario_id}'.")

        # 1. Synchronize simulated clock to event timestamp
        event_time = event.timestamp
        self.clock.set_simulated_time(event_time)

        # 2. Process observations through vision provider
        raw_obs_list: list[dict[str, Any]] = []
        if event.observations_json:
            try:
                raw_obs_list = json.loads(event.observations_json)
            except Exception:
                raw_obs_list = []

        validated_observations: list[SegmentObservation] = []
        for raw_item in raw_obs_list:
            parsed = self.vision.process_observation_payload(raw_item)
            validated_observations.extend(parsed)

        # 3. Ingest observations through observation service
        affected, alerts = self.obs_service.ingest_observations_bulk(
            validated_observations,
            as_of=event_time,
        )

        # 4. Update scenario state in database
        self.repo.update_scenario_progress(
            scenario_id=scenario_id,
            current_step=next_step,
            simulated_time=event_time,
        )

        return {
            "scenario_id": scenario_id,
            "time_step": next_step,
            "timestamp": event_time.isoformat() if event_time else None,
            "description": event.description,
            "observations_count": len(validated_observations),
            "affected_segments": affected.affected_segment_ids,
            "previous_statuses": {k: v.value for k, v in affected.previous_statuses.items()},
            "new_statuses": {k: v.value for k, v in affected.new_statuses.items()},
            "alerts": [
                {
                    "route_id": a.route_id,
                    "alert_type": a.alert_type,
                    "segment_id": a.segment_id,
                    "message": a.message,
                    "severity": a.severity,
                }
                for a in alerts.alerts
            ],
        }

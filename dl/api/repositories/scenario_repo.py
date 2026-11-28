"""
Repository for Scenario and ScenarioEvent database operations.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from dl.api.models import Scenario, ScenarioEvent


class ScenarioRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_scenarios(self) -> list[Scenario]:
        return self.db.query(Scenario).all()

    def get_scenario(self, scenario_id: str) -> Scenario | None:
        return self.db.query(Scenario).filter(Scenario.id == scenario_id).first()

    def get_events(self, scenario_id: str) -> list[ScenarioEvent]:
        return (
            self.db.query(ScenarioEvent)
            .filter(ScenarioEvent.scenario_id == scenario_id)
            .order_by(ScenarioEvent.id.asc())
            .all()
        )

    def get_event_by_step(self, scenario_id: str, time_step: str) -> ScenarioEvent | None:
        return (
            self.db.query(ScenarioEvent)
            .filter(ScenarioEvent.scenario_id == scenario_id, ScenarioEvent.time_step == time_step)
            .first()
        )

    def upsert_scenario(self, scenario: Scenario) -> Scenario:
        existing = self.get_scenario(scenario.id)
        if existing:
            existing.description = scenario.description
            existing.city_id = scenario.city_id
            existing.cameras_json = scenario.cameras_json
            self.db.commit()
            self.db.refresh(existing)
            return existing
        self.db.add(scenario)
        self.db.commit()
        self.db.refresh(scenario)
        return scenario

    def upsert_events(self, events: list[ScenarioEvent]) -> None:
        for ev in events:
            existing = self.get_event_by_step(ev.scenario_id, ev.time_step)
            if existing:
                existing.description = ev.description
                existing.timestamp = ev.timestamp
                existing.observations_json = ev.observations_json
            else:
                self.db.add(ev)
        self.db.commit()

    def update_scenario_progress(
        self,
        scenario_id: str,
        current_step: str,
        simulated_time: datetime | None,
    ) -> Scenario | None:
        existing = self.get_scenario(scenario_id)
        if existing:
            existing.current_time_step = current_step
            existing.current_simulated_time = simulated_time
            self.db.commit()
            self.db.refresh(existing)
        return existing

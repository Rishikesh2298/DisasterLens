"""
Observation service orchestrating ingestion, persistence, fusion, and route alert triggers.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from dl.api.models import Observation as ObservationModel
from dl.api.repositories.observation_repo import ObservationRepository
from dl.api.repositories.route_repo import RouteRepository
from dl.contracts.observation import AffectedSegments, RouteAlerts, SegmentObservation
from dl.routing.fusion import ObservationFusionEngine


class ObservationService:
    """
    Coordinates observation ingestion with the database and in-memory fusion engine.
    """

    def __init__(self, db: Session, fusion_engine: ObservationFusionEngine) -> None:
        self.db = db
        self.repo = ObservationRepository(db)
        self.route_repo = RouteRepository(db)
        self.fusion = fusion_engine

    def _get_tracked_routes(self) -> list[dict[str, Any]]:
        """Loads active saved routes for alert detection."""
        saved_routes = self.route_repo.get_saved_routes(active_only=True)
        tracked: list[dict[str, Any]] = []
        for r in saved_routes:
            try:
                seg_path = json.loads(r.segment_path_json)
            except Exception:
                seg_path = []
            tracked.append({
                "route_id": r.id,
                "segment_path": seg_path,
            })
        return tracked

    def ingest_observation(
        self,
        observation: SegmentObservation,
        as_of: datetime | None = None,
    ) -> tuple[AffectedSegments, RouteAlerts]:
        """
        Persists a single observation, feeds into fusion engine, and persists any generated alerts.
        """
        return self.ingest_observations_bulk([observation], as_of=as_of)

    def ingest_observations_bulk(
        self,
        observations: list[SegmentObservation],
        as_of: datetime | None = None,
    ) -> tuple[AffectedSegments, RouteAlerts]:
        """
        Persists a batch of observations, updates the fusion engine, and saves generated alerts.
        """
        if not observations:
            return (
                AffectedSegments(observation_id="empty", affected_segment_ids=[], previous_statuses={}, new_statuses={}),
                RouteAlerts(alerts=[]),
            )

        # 1. Persist observations to database for audit and permanent history
        self.repo.add_observations_bulk(observations)

        # 2. Ingest into fusion engine with active saved routes
        tracked_routes = self._get_tracked_routes()
        affected, alerts = self.fusion.ingest_observations_bulk(
            observations,
            as_of=as_of,
            tracked_routes=tracked_routes,
        )

        # 3. Persist route alerts if any were generated
        if alerts.alerts:
            self.route_repo.add_alerts_bulk(alerts.alerts)

        return affected, alerts

    def get_segment_history(
        self,
        segment_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ObservationModel]:
        """Returns observation history ordered by captured_at ascending."""
        return self.repo.get_segment_history(segment_id, limit=limit, offset=offset)

    def populate_fusion_from_db(self) -> None:
        """Hydrates the in-memory fusion engine from persisted observation history."""
        db_obs_list = self.repo.get_all_observations()
        for db_obs in db_obs_list:
            contract_obs = self.repo.to_contract(db_obs)
            # Add directly to history list without re-triggering alerts
            if contract_obs.segment_id not in self.fusion._history:
                self.fusion._history[contract_obs.segment_id] = []
            self.fusion._history[contract_obs.segment_id].append(contract_obs)

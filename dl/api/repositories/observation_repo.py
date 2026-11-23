"""
Repository for observation ingestion and history retrieval.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from dl.api.models import Observation
from dl.contracts.observation import SegmentObservation
from dl.contracts.scene import HazardType, RoadStatus, Zone
from dl.routing.freshness import normalize_datetime


class ObservationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add_observation(self, obs: SegmentObservation) -> Observation:
        """Persists a validated SegmentObservation to the database."""
        evidence_str = json.dumps(obs.evidence) if obs.evidence is not None else None
        affected_str = json.dumps(obs.affected_segments) if obs.affected_segments else None
        db_obs = Observation(
            observation_id=obs.observation_id,
            segment_id=obs.segment_id,
            source=obs.source,
            zone=obs.zone.value if isinstance(obs.zone, Zone) else str(obs.zone),
            verdict=obs.verdict.value if isinstance(obs.verdict, RoadStatus) else str(obs.verdict),
            confidence=obs.confidence,
            max_coverage=obs.max_coverage,
            hazard_type=obs.hazard_type.value if isinstance(obs.hazard_type, HazardType) else (str(obs.hazard_type) if obs.hazard_type else None),
            near_miss=obs.near_miss,
            recovery=obs.recovery,
            visibility=obs.visibility or "full",
            direct_verdict=obs.direct_verdict.value if obs.direct_verdict else None,
            mapped_verdict=obs.mapped_verdict.value if obs.mapped_verdict else None,
            evidence_json=evidence_str,
            captured_at=normalize_datetime(obs.captured_at),
            uploaded_at=normalize_datetime(obs.uploaded_at) if obs.uploaded_at else normalize_datetime(datetime.now()),
            analyzed_at=normalize_datetime(obs.analyzed_at) if obs.analyzed_at else None,
            model_id=obs.model_id,
            is_mock=obs.is_mock,
            image_path=obs.image_path,
            original_filename=obs.original_filename,
            affected_segments_json=affected_str,
        )
        self.db.add(db_obs)
        self.db.commit()
        self.db.refresh(db_obs)
        return db_obs

    def add_observations_bulk(self, obs_list: list[SegmentObservation]) -> list[Observation]:
        """Persists multiple observations in a single transaction."""
        db_items: list[Observation] = []
        for obs in obs_list:
            evidence_str = json.dumps(obs.evidence) if obs.evidence is not None else None
            affected_str = json.dumps(obs.affected_segments) if obs.affected_segments else None
            db_obs = Observation(
                observation_id=obs.observation_id,
                segment_id=obs.segment_id,
                source=obs.source,
                zone=obs.zone.value if isinstance(obs.zone, Zone) else str(obs.zone),
                verdict=obs.verdict.value if isinstance(obs.verdict, RoadStatus) else str(obs.verdict),
                confidence=obs.confidence,
                max_coverage=obs.max_coverage,
                hazard_type=obs.hazard_type.value if isinstance(obs.hazard_type, HazardType) else (str(obs.hazard_type) if obs.hazard_type else None),
                near_miss=obs.near_miss,
                recovery=obs.recovery,
                visibility=obs.visibility or "full",
                direct_verdict=obs.direct_verdict.value if obs.direct_verdict else None,
                mapped_verdict=obs.mapped_verdict.value if obs.mapped_verdict else None,
                evidence_json=evidence_str,
                captured_at=normalize_datetime(obs.captured_at),
                uploaded_at=normalize_datetime(obs.uploaded_at) if obs.uploaded_at else normalize_datetime(datetime.now()),
                analyzed_at=normalize_datetime(obs.analyzed_at) if obs.analyzed_at else None,
                model_id=obs.model_id,
                is_mock=obs.is_mock,
                image_path=obs.image_path,
                original_filename=obs.original_filename,
                affected_segments_json=affected_str,
            )
            self.db.add(db_obs)
            db_items.append(db_obs)
        self.db.commit()
        for item in db_items:
            self.db.refresh(item)
        return db_items

    def get_segment_history(
        self,
        segment_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Observation]:
        """Returns observation history for a segment, strictly ordered by captured_at ascending."""
        return (
            self.db.query(Observation)
            .filter(Observation.segment_id == segment_id)
            .order_by(Observation.captured_at.asc(), Observation.id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_all_observations(self) -> list[Observation]:
        """Returns all observations ordered by captured_at ascending."""
        return (
            self.db.query(Observation)
            .order_by(Observation.captured_at.asc(), Observation.id.asc())
            .all()
        )

    def to_contract(self, db_obs: Observation) -> SegmentObservation:
        """Converts an Observation ORM model to a SegmentObservation contract."""
        evidence = json.loads(db_obs.evidence_json) if db_obs.evidence_json else None
        aff_segs = json.loads(db_obs.affected_segments_json) if getattr(db_obs, "affected_segments_json", None) else []
        return SegmentObservation(
            observation_id=db_obs.observation_id,
            segment_id=db_obs.segment_id,
            source=db_obs.source,
            zone=Zone(db_obs.zone),
            captured_at=db_obs.captured_at,
            uploaded_at=db_obs.uploaded_at,
            analyzed_at=getattr(db_obs, "analyzed_at", None),
            verdict=RoadStatus(db_obs.verdict),
            confidence=db_obs.confidence,
            max_coverage=db_obs.max_coverage,
            hazard_type=HazardType(db_obs.hazard_type) if db_obs.hazard_type else None,
            near_miss=db_obs.near_miss,
            recovery=db_obs.recovery,
            visibility=db_obs.visibility,
            direct_verdict=RoadStatus(db_obs.direct_verdict) if db_obs.direct_verdict else None,
            mapped_verdict=RoadStatus(db_obs.mapped_verdict) if db_obs.mapped_verdict else None,
            evidence=evidence,
            model_id=getattr(db_obs, "model_id", None),
            is_mock=getattr(db_obs, "is_mock", True),
            image_path=getattr(db_obs, "image_path", None),
            original_filename=getattr(db_obs, "original_filename", None),
            affected_segments=aff_segs,
        )

"""
FastAPI dependency injection providers for DisasterLens services and database sessions.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from dl.api.config import settings
from dl.api.database import get_db
from dl.api.services.city_service import CityService
from dl.api.services.clock_service import ClockService, global_clock
from dl.api.services.observation_service import ObservationService
from dl.api.services.routing_service import RoutingService
from dl.api.services.scenario_service import ScenarioService
from dl.api.storage import ImageStorageService
from dl.routing.fusion import ObservationFusionEngine
from dl.vision.provider import get_vision_provider

# App-lifetime singleton fusion engine
app_fusion_engine = ObservationFusionEngine()


def get_storage_service() -> ImageStorageService:
    """Provides the local image storage service."""
    return ImageStorageService(
        upload_dir=settings.UPLOAD_DIR,
        max_size_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
    )


def get_db_session() -> Generator[Session, None, None]:
    """Provides a transactional database session."""
    yield from get_db()


def get_fusion_engine() -> ObservationFusionEngine:
    """Provides the shared in-memory observation fusion engine."""
    return app_fusion_engine


def get_clock_service() -> ClockService:
    """Provides the simulated clock service."""
    return global_clock


def get_city_service(
    db: Session = Depends(get_db_session),
    fusion: ObservationFusionEngine = Depends(get_fusion_engine),
) -> CityService:
    return CityService(db=db, fusion_engine=fusion)


def get_observation_service(
    db: Session = Depends(get_db_session),
    fusion: ObservationFusionEngine = Depends(get_fusion_engine),
) -> ObservationService:
    return ObservationService(db=db, fusion_engine=fusion)


def get_routing_service(
    db: Session = Depends(get_db_session),
    city_service: CityService = Depends(get_city_service),
    clock_service: ClockService = Depends(get_clock_service),
    fusion: ObservationFusionEngine = Depends(get_fusion_engine),
) -> RoutingService:
    return RoutingService(
        db=db,
        city_service=city_service,
        clock_service=clock_service,
        fusion_engine=fusion,
    )


def get_scenario_service(
    db: Session = Depends(get_db_session),
    obs_service: ObservationService = Depends(get_observation_service),
    clock_service: ClockService = Depends(get_clock_service),
) -> ScenarioService:
    provider = get_vision_provider(settings.VISION_MODE, model=settings.VISION_MODEL)
    return ScenarioService(
        db=db,
        observation_service=obs_service,
        clock_service=clock_service,
        vision_provider=provider,
    )

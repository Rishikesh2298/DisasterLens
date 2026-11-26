"""
DisasterLens FastAPI Application Entrypoint.

Provides the unified REST API for benchmark evaluation results, scenario playback,
observation ingestion, road network state, and condition-aware route recommendations.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dl.api.config import settings
from dl.api.database import SessionLocal, init_db
from dl.api.dependencies import app_fusion_engine
from dl.api.routers import cities, clock, observations, routes, scenarios, segments
from dl.api.routers import health as health_router
from dl.api.routers.benchmark import router as benchmark_router
from dl.api.seed import seed_demo_city
from dl.api.services.observation_service import ObservationService

# Export configured CORS origins at module level for inspection and compatibility
origins: list[str] = (
    settings.CORS_ORIGINS
    if isinstance(settings.CORS_ORIGINS, list)
    else [settings.CORS_ORIGINS]
)


def health() -> dict[str, object]:
    """Liveness payload for benchmark API compatibility checks."""
    return {"status": "ok", "service": "benchmark", "synthetic_only": True}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup and shutdown lifecycle management:
    - Initializes SQLite/PostgreSQL schema
    - Idempotently seeds demo city assets (36 nodes, 60 edges, T0–T3 scenario)
    - Hydrates in-memory fusion engine from database history
    """
    # 1. Initialize schema
    init_db()

    # 2. Idempotent seed
    with SessionLocal() as db:
        try:
            seed_demo_city(db)
        except Exception:
            # Non-fatal if scene file is not in standard path during isolated tests
            pass

        # 3. Hydrate fusion engine from persisted observation history
        try:
            obs_svc = ObservationService(db, app_fusion_engine)
            obs_svc.populate_fusion_from_db()
        except Exception:
            pass

    yield


def create_app() -> FastAPI:
    """
    Factory creating configured FastAPI instance.
    """
    app = FastAPI(
        title="DisasterLens Backend API",
        version="0.1.0",
        description=(
            "Synthetic disaster-city benchmark and demonstration application. "
            "Backend supporting benchmark results, road graph construction, observation fusion, "
            "freshness decay, and condition-aware route recommendation."
        ),
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount backend API routers under /api
    prefix = settings.API_PREFIX or "/api"
    app.include_router(health_router.router, prefix=prefix)
    app.include_router(cities.router, prefix=prefix)
    app.include_router(segments.router, prefix=prefix)
    app.include_router(observations.router, prefix=prefix)
    app.include_router(routes.router, prefix=prefix)
    app.include_router(scenarios.router, prefix=prefix)
    app.include_router(clock.router, prefix=prefix)

    # Mount benchmark results router (already prefixed with /api/benchmark)
    app.include_router(benchmark_router)
    app.add_api_route(
        "/api/benchmark/health", health, methods=["GET"], tags=["benchmark"]
    )

    # Global structured error handling
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "detail": str(exc),
                "path": request.url.path,
            },
        )

    return app


# Application instance for ASGI servers (uvicorn dl.api.main:app)
app = create_app()

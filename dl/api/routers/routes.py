"""
Routing router providing baseline and condition-aware recommended routes.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dl.api.dependencies import get_routing_service
from dl.api.services.routing_service import RoutingService
from dl.contracts.routing import RouteRecommendation

router = APIRouter(prefix="/routes", tags=["routes"])


class RouteRecommendRequest(BaseModel):
    city_id: str = Field("DEMO-001", description="City identifier")
    origin: str = Field(..., description="Origin intersection ID (e.g. 'N1')")
    destination: str = Field(..., description="Destination intersection ID (e.g. 'N36')")
    as_of: datetime | None = Field(None, description="Reference evaluation timestamp")
    risk_mode: str = Field("normal", description="Routing risk mode ('normal')")
    save_as: str | None = Field(None, description="Optional ID to save/track this route for alert monitoring")
    route_name: str | None = Field(None, description="Optional human-readable route label")


@router.post("/recommend", response_model=RouteRecommendation)
def recommend_route(
    req: RouteRecommendRequest,
    routing_service: RoutingService = Depends(get_routing_service),
) -> RouteRecommendation:
    """
    Computes shortest physical baseline, condition-aware recommended route (avoiding fresh BLOCKED segments),
    and up to 2 alternative paths. Evaluates freshness and costs against as_of or simulated clock.
    """
    try:
        rec = routing_service.recommend_route(
            city_id=req.city_id,
            origin=req.origin,
            destination=req.destination,
            as_of=req.as_of,
            risk_mode=req.risk_mode,
            save_as=req.save_as,
            route_name=req.route_name,
        )
        return rec
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Routing recommendation error: {e!s}")

"""
Routing service orchestrating graph retrieval, fusion state lookups, and route recommendation.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from dl.api.repositories.route_repo import RouteRepository
from dl.api.services.city_service import CityService
from dl.api.services.clock_service import ClockService
from dl.contracts.routing import RouteRecommendation
from dl.routing.fusion import ObservationFusionEngine
from dl.routing.recommend import recommend


class RoutingService:
    """
    Coordinates route recommendation between RoadGraph, fusion state, and persistence.
    """

    def __init__(
        self,
        db: Session,
        city_service: CityService,
        clock_service: ClockService,
        fusion_engine: ObservationFusionEngine,
    ) -> None:
        self.db = db
        self.city_service = city_service
        self.clock_service = clock_service
        self.fusion = fusion_engine
        self.route_repo = RouteRepository(db)

    def recommend_route(
        self,
        city_id: str,
        origin: str,
        destination: str,
        as_of: datetime | None = None,
        risk_mode: str = "normal",
        save_as: str | None = None,
        route_name: str | None = None,
    ) -> RouteRecommendation:
        """
        Calculates baseline and condition-aware recommended routes.
        Optionally persists the recommended route as a tracked SavedRoute.
        """
        # 1. Resolve reference time
        eval_as_of = self.clock_service.resolve_as_of(as_of)

        # 2. Retrieve cached RoadGraph
        road_graph = self.city_service.get_road_graph(city_id)

        # 3. Retrieve all effective segment statuses at eval_as_of
        all_segments = self.city_service.get_road_segments(city_id)
        seg_ids = [s.id for s in all_segments]
        segment_states = self.fusion.get_all_effective_states(eval_as_of, all_segment_ids=seg_ids)

        # 4. Call existing pure routing recommendation engine
        rec = recommend(
            graph=road_graph,
            origin=origin,
            destination=destination,
            segment_states=segment_states,
            as_of=eval_as_of,
            risk_mode=risk_mode,
        )

        # 5. Persist saved route if requested and recommendation succeeded
        if save_as and rec.recommended_route is not None:
            r = rec.recommended_route
            self.route_repo.save_route(
                route_id=save_as,
                city_id=city_id,
                origin_node=rec.origin,
                destination_node=rec.destination,
                node_path=r.node_path,
                segment_path=r.segment_path,
                length_m=r.total_length_m,
                cost=r.total_cost,
                name=route_name or f"Route {rec.origin}->{rec.destination}",
            )

        return rec

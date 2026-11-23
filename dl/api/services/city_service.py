"""
City service managing city data, graph caching, and segment status queries.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from dl.api.config import settings
from dl.api.models import City
from dl.api.models import Intersection as IntersectionModel
from dl.api.models import RoadSegment as RoadSegmentModel
from dl.api.repositories.city_repo import CityRepository
from dl.contracts.scene import (
    Difficulty,
    Point,
    Scene,
    Zone,
)
from dl.contracts.scene import (
    Intersection as IntersectionContract,
)
from dl.contracts.scene import (
    RoadSegment as RoadSegmentContract,
)
from dl.routing.freshness import EffectiveRoadStatus
from dl.routing.fusion import ObservationFusionEngine
from dl.routing.graph import RoadGraph


class CityService:
    """
    Manages cities, road graphs, and effective segment states.
    Maintains an in-memory graph cache to avoid rebuilding NetworkX graphs on every request.
    """

    def __init__(self, db: Session, fusion_engine: ObservationFusionEngine) -> None:
        self.db = db
        self.repo = CityRepository(db)
        self.fusion = fusion_engine
        self._graph_cache: dict[str, RoadGraph] = {}

    def get_city(self, city_id: str) -> City | None:
        return self.repo.get_city(city_id)

    def list_cities(self) -> list[City]:
        return self.repo.list_cities()

    def get_intersections(self, city_id: str) -> list[IntersectionModel]:
        return self.repo.get_intersections(city_id)

    def get_road_segments(self, city_id: str) -> list[RoadSegmentModel]:
        return self.repo.get_road_segments(city_id)

    def get_road_graph(self, city_id: str) -> RoadGraph:
        """
        Retrieves or constructs and caches the RoadGraph for a city.
        """
        if city_id in self._graph_cache:
            return self._graph_cache[city_id]

        # 1. Try loading from database records
        city = self.repo.get_city(city_id)
        db_intersections = self.repo.get_intersections(city_id)
        db_segments = self.repo.get_road_segments(city_id)

        if city and db_intersections and db_segments:
            intersections = [
                IntersectionContract(id=i.id, x=i.x, y=i.y, zone=Zone(i.zone))
                for i in db_intersections
            ]
            segments = [
                RoadSegmentContract(
                    id=s.id,
                    node_a=s.from_intersection_id,
                    node_b=s.to_intersection_id,
                    length_m=s.length_m,
                    width_px=40.0,
                    zone=Zone(s.zone),
                    centerline=[Point(x=p[0], y=p[1]) for p in json.loads(s.centerline_json)],
                    polygon=[Point(x=p[0], y=p[1]) for p in json.loads(s.polygon_json)],
                )
                for s in db_segments
            ]
            scene = Scene(
                scene_id="DEMO-001",
                seed=20261127,
                difficulty=Difficulty.EASY,
                grid_size=city.grid_size,
                image_width=int(city.bounds_x_max),
                image_height=int(city.bounds_y_max),
                intersections=intersections,
                road_segments=segments,
                buildings=[],
                parks=[],
                hazards=[],
            )
            graph = RoadGraph.from_scene(scene)
            self._graph_cache[city_id] = graph
            return graph

        # 2. Fallback to demo_city scene file if available
        scene_file = Path(settings.DATA_DIR) / "scene.json"
        if scene_file.exists():
            graph = RoadGraph.from_json(scene_file)
            self._graph_cache[city_id] = graph
            return graph

        raise ValueError(f"Unable to construct road graph for city '{city_id}'. City data not found.")

    def get_segment_effective_states(
        self,
        city_id: str,
        as_of: datetime,
    ) -> dict[str, dict[str, Any]]:
        """
        Computes effective road condition for all segments in a city at reference time as_of.
        Returns UNKNOWN for segments without observations.
        """
        segments = self.repo.get_road_segments(city_id)
        seg_ids = [s.id for s in segments]

        # Query fusion engine for all segment states
        effective_map = self.fusion.get_all_effective_states(as_of, all_segment_ids=seg_ids)

        results: dict[str, dict[str, Any]] = {}
        for sid in seg_ids:
            eff: EffectiveRoadStatus = effective_map.get(sid, EffectiveRoadStatus(
                status="UNKNOWN", freshness="unknown", age_hours=None, is_stale_from_blocked=False
            ))
            results[sid] = {
                "segment_id": sid,
                "status": eff.status.value if hasattr(eff.status, "value") else str(eff.status),
                "freshness": eff.freshness,
                "age_hours": eff.age_hours,
                "is_stale_from_blocked": eff.is_stale_from_blocked,
                "original_verdict": eff.original_verdict.value if eff.original_verdict else None,
                "captured_at": eff.captured_at.isoformat() if eff.captured_at else None,
            }
        return results

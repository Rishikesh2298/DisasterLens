"""
Repository for City, Intersection, and RoadSegment queries.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from dl.api.models import City, Intersection, RoadSegment


class CityRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_city(self, city_id: str) -> City | None:
        return self.db.query(City).filter(City.id == city_id).first()

    def list_cities(self) -> list[City]:
        return self.db.query(City).all()

    def get_intersections(self, city_id: str) -> list[Intersection]:
        return self.db.query(Intersection).filter(Intersection.city_id == city_id).all()

    def get_road_segments(self, city_id: str) -> list[RoadSegment]:
        return self.db.query(RoadSegment).filter(RoadSegment.city_id == city_id).all()

    def get_segment(self, segment_id: str) -> RoadSegment | None:
        return self.db.query(RoadSegment).filter(RoadSegment.id == segment_id).first()

    def upsert_city(self, city: City) -> City:
        existing = self.get_city(city.id)
        if existing:
            existing.name = city.name
            existing.grid_size = city.grid_size
            existing.bounds_x_min = city.bounds_x_min
            existing.bounds_x_max = city.bounds_x_max
            existing.bounds_y_min = city.bounds_y_min
            existing.bounds_y_max = city.bounds_y_max
            self.db.commit()
            self.db.refresh(existing)
            return existing
        self.db.add(city)
        self.db.commit()
        self.db.refresh(city)
        return city

    def upsert_intersections(self, intersections: list[Intersection]) -> None:
        for item in intersections:
            existing = self.db.query(Intersection).filter(Intersection.id == item.id).first()
            if existing:
                existing.x = item.x
                existing.y = item.y
                existing.zone = item.zone
            else:
                self.db.add(item)
        self.db.commit()

    def upsert_road_segments(self, segments: list[RoadSegment]) -> None:
        for seg in segments:
            existing = self.db.query(RoadSegment).filter(RoadSegment.id == seg.id).first()
            if existing:
                existing.from_intersection_id = seg.from_intersection_id
                existing.to_intersection_id = seg.to_intersection_id
                existing.length_m = seg.length_m
                existing.zone = seg.zone
                existing.centerline_json = seg.centerline_json
                existing.polygon_json = seg.polygon_json
            else:
                self.db.add(seg)
        self.db.commit()

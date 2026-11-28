"""
Repository for SavedRoute and RouteAlert database operations.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from dl.api.models import RouteAlert as RouteAlertModel
from dl.api.models import SavedRoute as SavedRouteModel
from dl.contracts.observation import RouteAlert


class RouteRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_route(
        self,
        route_id: str,
        city_id: str,
        origin_node: str,
        destination_node: str,
        node_path: list[str],
        segment_path: list[str],
        length_m: float,
        cost: float,
        name: str | None = None,
    ) -> SavedRouteModel:
        existing = self.db.query(SavedRouteModel).filter(SavedRouteModel.id == route_id).first()
        node_json = json.dumps(node_path)
        seg_json = json.dumps(segment_path)
        if existing:
            existing.city_id = city_id
            existing.origin_node = origin_node
            existing.destination_node = destination_node
            existing.node_path_json = node_json
            existing.segment_path_json = seg_json
            existing.length_m = length_m
            existing.cost = cost
            existing.name = name or existing.name
            self.db.commit()
            self.db.refresh(existing)
            return existing

        route = SavedRouteModel(
            id=route_id,
            city_id=city_id,
            origin_node=origin_node,
            destination_node=destination_node,
            node_path_json=node_json,
            segment_path_json=seg_json,
            length_m=length_m,
            cost=cost,
            name=name,
            is_active=True,
        )
        self.db.add(route)
        self.db.commit()
        self.db.refresh(route)
        return route

    def get_saved_routes(self, city_id: str | None = None, active_only: bool = True) -> list[SavedRouteModel]:
        query = self.db.query(SavedRouteModel)
        if city_id:
            query = query.filter(SavedRouteModel.city_id == city_id)
        if active_only:
            query = query.filter(SavedRouteModel.is_active.is_(True))
        return query.all()

    def get_saved_route(self, route_id: str) -> SavedRouteModel | None:
        return self.db.query(SavedRouteModel).filter(SavedRouteModel.id == route_id).first()

    def add_alert(self, alert: RouteAlert) -> RouteAlertModel:
        db_alert = RouteAlertModel(
            route_id=alert.route_id,
            segment_id=alert.segment_id,
            alert_type=alert.alert_type,
            message=alert.message,
            severity=alert.severity,
        )
        self.db.add(db_alert)
        self.db.commit()
        self.db.refresh(db_alert)
        return db_alert

    def add_alerts_bulk(self, alerts: list[RouteAlert]) -> list[RouteAlertModel]:
        db_items: list[RouteAlertModel] = []
        for a in alerts:
            db_alert = RouteAlertModel(
                route_id=a.route_id,
                segment_id=a.segment_id,
                alert_type=a.alert_type,
                message=a.message,
                severity=a.severity,
            )
            self.db.add(db_alert)
            db_items.append(db_alert)
        self.db.commit()
        for item in db_items:
            self.db.refresh(item)
        return db_items

    def get_alerts(self, route_id: str | None = None, limit: int = 50) -> list[RouteAlertModel]:
        query = self.db.query(RouteAlertModel)
        if route_id:
            query = query.filter(RouteAlertModel.route_id == route_id)
        return query.order_by(RouteAlertModel.created_at.desc(), RouteAlertModel.id.desc()).limit(limit).all()

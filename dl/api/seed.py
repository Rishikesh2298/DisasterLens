"""
Idempotent database seeder for DisasterLens demo city.

Loads:
- City metadata (DEMO-001)
- 36 intersections
- 60 road segments
- Scenario definition (demo_city) and T0–T3 events
- Default active saved route (ROUTE-DISPATCH-01) for alert verification
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from dl.api.config import settings
from dl.api.database import SessionLocal, init_db
from dl.api.models import (
    City,
)
from dl.api.models import (
    Intersection as IntersectionModel,
)
from dl.api.models import (
    RoadSegment as RoadSegmentModel,
)
from dl.api.models import (
    SavedRoute as SavedRouteModel,
)
from dl.api.models import (
    Scenario as ScenarioModel,
)
from dl.api.models import (
    ScenarioEvent as ScenarioEventModel,
)
from dl.contracts.scene import Scene
from dl.routing.freshness import normalize_datetime


def seed_demo_city(db: Session, data_dir: Path | None = None, force: bool = False) -> City:
    """
    Idempotently seeds DEMO-001 city, intersections, segments, scenario, and events.
    Does not duplicate records on repeated execution.
    """
    dir_path = Path(data_dir or settings.DATA_DIR)
    scene_file = dir_path / "scene.json"
    scenario_file = dir_path / "scenario.json"

    if not scene_file.exists():
        raise FileNotFoundError(f"Scene file not found at: {scene_file}")

    # Load and validate scene contract
    with open(scene_file, "r", encoding="utf-8") as f:
        scene_raw = json.load(f)
    scene = Scene.model_validate(scene_raw)

    city_id = scene.scene_id or "DEMO-001"
    city_name = "Disaster City Alpha"
    x_max = float(scene.image_width)
    y_max = float(scene.image_height)

    # 1. Upsert City
    existing_city = db.query(City).filter(City.id == city_id).first()
    if existing_city and not force:
        city = existing_city
    else:
        if not existing_city:
            city = City(
                id=city_id,
                name=city_name,
                grid_size=scene.grid_size,
                bounds_x_min=0.0,
                bounds_x_max=x_max,
                bounds_y_min=0.0,
                bounds_y_max=y_max,
            )
            db.add(city)
            db.commit()
            db.refresh(city)
        else:
            existing_city.name = city_name
            existing_city.grid_size = scene.grid_size
            existing_city.bounds_x_min = 0.0
            existing_city.bounds_x_max = x_max
            existing_city.bounds_y_min = 0.0
            existing_city.bounds_y_max = y_max
            existing_city.bounds_y_min = scene.bounds.y_min
            existing_city.bounds_y_max = scene.bounds.y_max
            db.commit()
            city = existing_city

    # 2. Upsert Intersections (36 nodes)
    for node in scene.intersections:
        existing_node = db.query(IntersectionModel).filter(IntersectionModel.id == node.id).first()
        if not existing_node:
            db_node = IntersectionModel(
                id=node.id,
                city_id=city.id,
                x=node.x,
                y=node.y,
                zone=node.zone.value,
            )
            db.add(db_node)
        else:
            existing_node.x = node.x
            existing_node.y = node.y
            existing_node.zone = node.zone.value
    db.commit()

    # 3. Upsert Road Segments (60 edges)
    for seg in scene.road_segments:
        existing_seg = db.query(RoadSegmentModel).filter(RoadSegmentModel.id == seg.id).first()
        centerline_json = json.dumps([[p.x, p.y] for p in seg.centerline])
        polygon_json = json.dumps([[p.x, p.y] for p in seg.polygon])
        if not existing_seg:
            db_seg = RoadSegmentModel(
                id=seg.id,
                city_id=city.id,
                from_intersection_id=seg.node_a,
                to_intersection_id=seg.node_b,
                length_m=seg.length_m,
                zone=seg.zone.value,
                centerline_json=centerline_json,
                polygon_json=polygon_json,
            )
            db.add(db_seg)
        else:
            existing_seg.from_intersection_id = seg.node_a
            existing_seg.to_intersection_id = seg.node_b
            existing_seg.length_m = seg.length_m
            existing_seg.zone = seg.zone.value
            existing_seg.centerline_json = centerline_json
            existing_seg.polygon_json = polygon_json
    db.commit()

    # 4. Upsert Scenario and Events if scenario.json is present
    if scenario_file.exists():
        with open(scenario_file, "r", encoding="utf-8") as f:
            scenario_raw = json.load(f)

        scenario_id = scenario_raw.get("scenario_id", "demo_city")
        desc = scenario_raw.get("description", "DisasterLens Demo City Scenario")
        cameras = json.dumps(scenario_raw.get("cameras", []))

        existing_scen = db.query(ScenarioModel).filter(ScenarioModel.id == scenario_id).first()
        if not existing_scen:
            scen = ScenarioModel(
                id=scenario_id,
                city_id=city.id,
                description=desc,
                current_time_step="T0",
                cameras_json=cameras,
            )
            db.add(scen)
            db.commit()
            db.refresh(scen)
        else:
            existing_scen.description = desc
            existing_scen.cameras_json = cameras
            db.commit()
            scen = existing_scen

        # Events (T0..T3)
        events_data = scenario_raw.get("events", [])
        for ev in events_data:
            step = ev.get("time_step", "T0")
            ts_raw = ev.get("timestamp")
            dt = normalize_datetime(datetime.fromisoformat(ts_raw)) if ts_raw else None
            ev_desc = ev.get("description", "")
            obs_json = json.dumps(ev.get("observations", []))

            existing_ev = (
                db.query(ScenarioEventModel)
                .filter(ScenarioEventModel.scenario_id == scen.id, ScenarioEventModel.time_step == step)
                .first()
            )
            if not existing_ev:
                db_ev = ScenarioEventModel(
                    scenario_id=scen.id,
                    time_step=step,
                    timestamp=dt,
                    description=ev_desc,
                    observations_json=obs_json,
                )
                db.add(db_ev)
            else:
                existing_ev.timestamp = dt
                existing_ev.description = ev_desc
                existing_ev.observations_json = obs_json
        db.commit()

    # 5. Upsert Default Tracked Saved Route for Alert Verification
    route_id = "ROUTE-DISPATCH-01"
    existing_route = db.query(SavedRouteModel).filter(SavedRouteModel.id == route_id).first()
    if not existing_route:
        # Route along northern corridor N1 -> N6 crossing SEG-001..SEG-005
        default_route = SavedRouteModel(
            id=route_id,
            city_id=city.id,
            name="Primary Emergency Dispatch Route (North Corridor)",
            origin_node="N1",
            destination_node="N6",
            node_path_json=json.dumps(["N1", "N2", "N3", "N4", "N5", "N6"]),
            segment_path_json=json.dumps(["SEG-001", "SEG-002", "SEG-003", "SEG-004", "SEG-005"]),
            length_m=172.8,
            cost=172.8,
            is_active=True,
        )
        db.add(default_route)
        db.commit()

    return city


if __name__ == "__main__":
    init_db()
    with SessionLocal() as db_session:
        city = seed_demo_city(db_session)
        print(f"Successfully seeded demo city: {city.id} ({city.name}) with 36 intersections and 60 segments.")

"""
City router providing city metadata, intersection/segment listings, and effective segment states.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from dl.api.dependencies import get_city_service, get_clock_service
from dl.api.services.city_service import CityService
from dl.api.services.clock_service import ClockService

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("")
def list_cities(
    city_service: CityService = Depends(get_city_service),
) -> list[dict[str, Any]]:
    """Lists all available cities in the system."""
    cities = city_service.list_cities()
    return [
        {
            "id": c.id,
            "name": c.name,
            "grid_size": c.grid_size,
            "bounds": {
                "x_min": c.bounds_x_min,
                "x_max": c.bounds_x_max,
                "y_min": c.bounds_y_min,
                "y_max": c.bounds_y_max,
            },
        }
        for c in cities
    ]


@router.get("/{city_id}")
def get_city(
    city_id: str,
    city_service: CityService = Depends(get_city_service),
) -> dict[str, Any]:
    """Retrieves full city metadata, graph topology, zones, geometry, and image URLs."""
    city = city_service.get_city(city_id)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_id}' not found.")

    intersections = city_service.get_intersections(city_id)
    segments = city_service.get_road_segments(city_id)

    # Derive zones from intersections and segments
    zones = sorted({i.zone for i in intersections} | {s.zone for s in segments})

    # Map connected segments per intersection for graph topology
    node_to_segs: dict[str, list[str]] = {}
    for s in segments:
        node_to_segs.setdefault(s.from_intersection_id, []).append(s.id)
        node_to_segs.setdefault(s.to_intersection_id, []).append(s.id)

    # Scene image URLs for demo city and dataset scenes
    if city_id in ("DEMO-001", "demo_city"):
        scene_image_urls = {
            "plain": "/scenarios/demo_city/image_plain.png",
            "labelled": "/scenarios/demo_city/image_labelled.png",
        }
        scene_image_url = "/scenarios/demo_city/image_plain.png"
    else:
        scene_image_urls = {
            "plain": f"/datasets/v1/{city_id}/image_plain.png",
            "labelled": f"/datasets/v1/{city_id}/image_labelled.png",
        }
        scene_image_url = f"/datasets/v1/{city_id}/image_plain.png"

    return {
        "id": city.id,
        "name": city.name,
        "grid_size": city.grid_size,
        "bounds": {
            "x_min": city.bounds_x_min,
            "x_max": city.bounds_x_max,
            "y_min": city.bounds_y_min,
            "y_max": city.bounds_y_max,
        },
        "zones": zones,
        "scene_image_url": scene_image_url,
        "scene_image_urls": scene_image_urls,
        "graph": {
            "node_count": len(intersections),
            "edge_count": len(segments),
            "is_connected": True,
        },
        "intersections_count": len(intersections),
        "segments_count": len(segments),
        "intersections": [
            {
                "id": i.id,
                "x": i.x,
                "y": i.y,
                "zone": i.zone,
                "connected_segments": sorted(node_to_segs.get(i.id, [])),
            }
            for i in intersections
        ],
        "road_segments": [
            {
                "id": s.id,
                "from_intersection": s.from_intersection_id,
                "to_intersection": s.to_intersection_id,
                "node_a": s.from_intersection_id,
                "node_b": s.to_intersection_id,
                "length_m": s.length_m,
                "zone": s.zone,
                "centerline": [
                    {"x": p[0], "y": p[1]} if isinstance(p, (list, tuple)) else p
                    for p in json.loads(s.centerline_json)
                ],
                "polygon": [
                    {"x": p[0], "y": p[1]} if isinstance(p, (list, tuple)) else p
                    for p in json.loads(s.polygon_json)
                ],
            }
            for s in segments
        ],
    }


@router.get("/{city_id}/segments")
def get_city_segments_status(
    city_id: str,
    as_of: datetime | None = Query(None, description="Evaluation reference timestamp (ISO-8601 UTC)"),
    city_service: CityService = Depends(get_city_service),
    clock: ClockService = Depends(get_clock_service),
) -> dict[str, Any]:
    """
    Returns effective condition, freshness, and age for all segments in the city evaluated at as_of.
    Respects supplied as_of or current simulated clock. Segments with no observations return UNKNOWN.
    """
    city = city_service.get_city(city_id)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_id}' not found.")

    eval_as_of = clock.resolve_as_of(as_of)
    segment_states = city_service.get_segment_effective_states(city_id, eval_as_of)

    return {
        "city_id": city_id,
        "as_of": eval_as_of.isoformat(),
        "segments_count": len(segment_states),
        "segments": segment_states,
    }

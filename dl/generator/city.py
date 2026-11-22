"""
Deterministic city grid generator.

Produces a grid of intersections connected by road segments, with buildings
and parks placed in the blocks between roads.

Scale: 1 pixel ≈ 0.2 metres  (5 px = 1 m).
Canvas: 1024 × 1024 pixels.
Road width: 40 px (≈ 8 m — a wide two-lane road).
Intersection extension: 20 px into each intersection.

Grid sizes:
  easy   → 4×4  (16 intersections, 24 road segments)
  medium → 5×5  (25 intersections, 40 road segments)
  hard   → 6×6  (36 intersections, 60 road segments)
"""

from __future__ import annotations

import random as _random
from typing import Optional

from shapely.geometry import box as shapely_box, Polygon as ShapelyPolygon

from dl.contracts.scene import (
    Building, Difficulty, Intersection, Park, Point, RoadSegment, Scene, Zone,
)


# ── Constants ─────────────────────────────────────────────────────────────

CANVAS = 1024
ROAD_WIDTH = 40
HALF_ROAD = ROAD_WIDTH // 2
INTERSECTION_EXTEND = 20
PIXEL_TO_METRE = 0.2  # 1 px ≈ 0.2 m
MARGIN = 80  # canvas margin so roads don't touch edges


def _zone(x: float, y: float, cx: float, cy: float) -> Zone:
    """Determine which quadrant (zone) a point falls in."""
    if x < cx:
        return Zone.NW if y < cy else Zone.SW
    return Zone.NE if y < cy else Zone.SE


def _grid_size_for_difficulty(difficulty: Difficulty) -> int:
    return {Difficulty.EASY: 4, Difficulty.MEDIUM: 5, Difficulty.HARD: 6}[difficulty]


def _poly_points(shapely_poly: ShapelyPolygon) -> list[Point]:
    """Convert Shapely polygon exterior to list[Point]."""
    coords = list(shapely_poly.exterior.coords)
    # Drop the closing duplicate
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [Point(x=round(c[0], 2), y=round(c[1], 2)) for c in coords]


# ── City Generator ────────────────────────────────────────────────────────

def generate_city(
    scene_id: str,
    seed: int,
    difficulty: Difficulty,
    hazards: Optional[list] = None,
) -> Scene:
    """Generate a deterministic synthetic city grid.

    Parameters
    ----------
    scene_id : e.g. "S-0001"
    seed : deterministic random seed
    difficulty : easy / medium / hard
    hazards : pre-built hazard list (injected by build pipeline)

    Returns
    -------
    Scene — complete scene model (minus hazards if not supplied).
    """
    rng = _random.Random(seed)
    grid = _grid_size_for_difficulty(difficulty)
    spacing = (CANVAS - 2 * MARGIN) / (grid - 1)
    cx = CANVAS / 2
    cy = CANVAS / 2

    # 1. Intersections (left-to-right, top-to-bottom)
    intersections: list[Intersection] = []
    node_idx = 1
    for row in range(grid):
        for col in range(grid):
            x = MARGIN + col * spacing
            y = MARGIN + row * spacing
            intersections.append(Intersection(
                id=f"N{node_idx}",
                x=round(x, 2),
                y=round(y, 2),
                zone=_zone(x, y, cx, cy),
            ))
            node_idx += 1

    # Build lookup: (row, col) → Intersection
    def _node(r: int, c: int) -> Intersection:
        return intersections[r * grid + c]

    # 2. Road segments
    segments: list[RoadSegment] = []
    seg_counter = 1

    for row in range(grid):
        for col in range(grid):
            na = _node(row, col)
            # Horizontal neighbour (right)
            if col < grid - 1:
                nb = _node(row, col + 1)
                seg_id = f"SEG-{seg_counter:03d}"
                seg_counter += 1
                # Centerline: extend 20 px into each intersection
                cl_start = Point(x=round(na.x - INTERSECTION_EXTEND, 2), y=round(na.y, 2))
                cl_end = Point(x=round(nb.x + INTERSECTION_EXTEND, 2), y=round(nb.y, 2))
                # Polygon: rectangle around road
                poly = shapely_box(
                    cl_start.x,
                    na.y - HALF_ROAD,
                    cl_end.x,
                    na.y + HALF_ROAD,
                )
                length_px = abs(nb.x - na.x)
                mid_x = (na.x + nb.x) / 2
                segments.append(RoadSegment(
                    id=seg_id,
                    node_a=na.id,
                    node_b=nb.id,
                    centerline=[cl_start, cl_end],
                    polygon=_poly_points(poly),
                    length_m=round(length_px * PIXEL_TO_METRE, 2),
                    width_px=ROAD_WIDTH,
                    zone=_zone(mid_x, na.y, cx, cy),
                ))
            # Vertical neighbour (down)
            if row < grid - 1:
                nb = _node(row + 1, col)
                seg_id = f"SEG-{seg_counter:03d}"
                seg_counter += 1
                cl_start = Point(x=round(na.x, 2), y=round(na.y - INTERSECTION_EXTEND, 2))
                cl_end = Point(x=round(na.x, 2), y=round(nb.y + INTERSECTION_EXTEND, 2))
                poly = shapely_box(
                    na.x - HALF_ROAD,
                    cl_start.y,
                    na.x + HALF_ROAD,
                    cl_end.y,
                )
                length_px = abs(nb.y - na.y)
                mid_y = (na.y + nb.y) / 2
                segments.append(RoadSegment(
                    id=seg_id,
                    node_a=na.id,
                    node_b=nb.id,
                    centerline=[cl_start, cl_end],
                    polygon=_poly_points(poly),
                    length_m=round(length_px * PIXEL_TO_METRE, 2),
                    width_px=ROAD_WIDTH,
                    zone=_zone(na.x, mid_y, cx, cy),
                ))

    # 3. Buildings — placed in grid blocks
    buildings: list[Building] = []
    building_counter = 1
    bldg_margin = 12  # gap between road edge and building

    for row in range(grid - 1):
        for col in range(grid - 1):
            tl = _node(row, col)
            br = _node(row + 1, col + 1)
            # Block interior region
            bx_min = tl.x + HALF_ROAD + bldg_margin
            by_min = tl.y + HALF_ROAD + bldg_margin
            bx_max = br.x - HALF_ROAD - bldg_margin
            by_max = br.y - HALF_ROAD - bldg_margin

            if bx_max - bx_min < 20 or by_max - by_min < 20:
                continue  # block too small

            block_cx = (bx_min + bx_max) / 2
            block_cy = (by_min + by_max) / 2

            # Place 1-2 buildings per block
            block_w = bx_max - bx_min
            block_h = by_max - by_min

            # First building: upper-left portion
            bw = rng.uniform(0.3, 0.45) * block_w
            bh = rng.uniform(0.3, 0.45) * block_h
            x1 = bx_min + rng.uniform(0, 0.1) * block_w
            y1 = by_min + rng.uniform(0, 0.1) * block_h
            poly = shapely_box(x1, y1, x1 + bw, y1 + bh)
            zone = _zone(block_cx, block_cy, cx, cy)
            buildings.append(Building(
                id=f"B-{building_counter:03d}",
                polygon=_poly_points(poly),
                zone=zone,
            ))
            building_counter += 1

            # Second building: lower-right portion
            bw2 = rng.uniform(0.3, 0.45) * block_w
            bh2 = rng.uniform(0.3, 0.45) * block_h
            x2 = bx_max - bw2 - rng.uniform(0, 0.1) * block_w
            y2 = by_max - bh2 - rng.uniform(0, 0.1) * block_h
            # Ensure no overlap with first building
            if x2 > x1 + bw + 4 or y2 > y1 + bh + 4:
                poly2 = shapely_box(x2, y2, x2 + bw2, y2 + bh2)
                buildings.append(Building(
                    id=f"B-{building_counter:03d}",
                    polygon=_poly_points(poly2),
                    zone=zone,
                ))
                building_counter += 1

    # 4. Parks — place a few parks (1 per difficulty level)
    parks: list[Park] = []
    park_counter = 1
    num_parks = {Difficulty.EASY: 1, Difficulty.MEDIUM: 2, Difficulty.HARD: 3}[difficulty]

    # Pick random empty blocks for parks
    all_blocks = []
    for row in range(grid - 1):
        for col in range(grid - 1):
            tl = _node(row, col)
            br = _node(row + 1, col + 1)
            bx_min = tl.x + HALF_ROAD + bldg_margin
            by_min = tl.y + HALF_ROAD + bldg_margin
            bx_max = br.x - HALF_ROAD - bldg_margin
            by_max = br.y - HALF_ROAD - bldg_margin
            if bx_max - bx_min >= 20 and by_max - by_min >= 20:
                block_cx = (bx_min + bx_max) / 2
                block_cy = (by_min + by_max) / 2
                all_blocks.append((bx_min, by_min, bx_max, by_max, block_cx, block_cy))

    rng.shuffle(all_blocks)
    for i in range(min(num_parks, len(all_blocks))):
        bx_min, by_min, bx_max, by_max, bcx, bcy = all_blocks[i]
        # Park covers most of the block
        px = bx_min + 4
        py = by_min + 4
        pw = (bx_max - bx_min) - 8
        ph = (by_max - by_min) - 8
        poly = shapely_box(px, py, px + pw, py + ph)
        parks.append(Park(
            id=f"P-{park_counter:03d}",
            polygon=_poly_points(poly),
            zone=_zone(bcx, bcy, cx, cy),
        ))
        park_counter += 1

    return Scene(
        scene_id=scene_id,
        seed=seed,
        difficulty=difficulty,
        grid_size=grid,
        intersections=intersections,
        road_segments=segments,
        buildings=buildings,
        parks=parks,
        hazards=hazards or [],
    )

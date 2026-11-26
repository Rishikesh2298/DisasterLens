"""
Road graph builder for DisasterLens using NetworkX.

Builds an undirected graph of city intersections and road segments
derived from synthetic scenes. Completely independent of web frameworks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx

from dl.generator.models import Intersection, RoadSegment, Scene


class RoadGraph:
    """
    Undirected road network graph representation.

    Attributes:
        graph: Underlying NetworkX Graph.
        scene_id: Identifier of the source scene.
        intersections: Map of node_id -> Intersection model.
        segments: Map of segment_id -> RoadSegment model.
        segment_to_edge: Map of segment_id -> (node_a, node_b).
        edge_to_segment: Map of (node_a, node_b) and (node_b, node_a) -> segment_id.
    """

    def __init__(
        self,
        scene_id: str,
        graph: nx.Graph,
        intersections: dict[str, Intersection],
        segments: dict[str, RoadSegment],
        segment_to_edge: dict[str, tuple[str, str]],
        edge_to_segment: dict[tuple[str, str], str],
    ) -> None:
        self.scene_id = scene_id
        self.graph = graph
        self.intersections = intersections
        self.segments = segments
        self.segment_to_edge = segment_to_edge
        self.edge_to_segment = edge_to_segment

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    @property
    def is_connected(self) -> bool:
        """Returns True if the road graph forms a single connected component."""
        if self.node_count == 0:
            return True
        return nx.is_connected(self.graph)

    def validate_connectivity(self) -> bool:
        """
        Validates graph connectivity without modifying the graph.
        Returns True if connected, False if disconnected.
        """
        return self.is_connected

    def get_edge_for_segment(self, segment_id: str) -> tuple[str, str]:
        """Returns the (node_a, node_b) endpoint tuple for a segment."""
        if segment_id not in self.segment_to_edge:
            raise KeyError(f"Segment '{segment_id}' not found in road graph.")
        return self.segment_to_edge[segment_id]

    def get_segment_for_edge(self, node_a: str, node_b: str) -> str:
        """Returns the segment_id for an undirected edge connecting two nodes."""
        key = (node_a, node_b)
        if key in self.edge_to_segment:
            return self.edge_to_segment[key]
        reverse_key = (node_b, node_a)
        if reverse_key in self.edge_to_segment:
            return self.edge_to_segment[reverse_key]
        raise KeyError(f"No segment found connecting edge ({node_a}, {node_b}).")

    @classmethod
    def from_scene(cls, scene: Scene) -> RoadGraph:
        """
        Constructs a RoadGraph from a validated Scene contract instance.

        Raises:
            ValueError: If duplicate node IDs, duplicate segment IDs, or
                        missing endpoints are detected.
        """
        G = nx.Graph()
        intersections_map: dict[str, Intersection] = {}
        segments_map: dict[str, RoadSegment] = {}
        segment_to_edge: dict[str, tuple[str, str]] = {}
        edge_to_segment: dict[tuple[str, str], str] = {}

        # 1. Add and validate nodes
        for node in scene.intersections:
            if node.id in intersections_map:
                raise ValueError(f"Duplicate intersection ID detected: '{node.id}'")
            intersections_map[node.id] = node
            G.add_node(
                node.id,
                x=node.x,
                y=node.y,
                zone=node.zone.value if hasattr(node.zone, "value") else str(node.zone),
            )

        # 2. Add and validate road segments
        for seg in scene.road_segments:
            if seg.id in segments_map:
                raise ValueError(f"Duplicate road segment ID detected: '{seg.id}'")
            if seg.node_a not in intersections_map:
                raise ValueError(
                    f"Road segment '{seg.id}' references missing endpoint node_a: '{seg.node_a}'"
                )
            if seg.node_b not in intersections_map:
                raise ValueError(
                    f"Road segment '{seg.id}' references missing endpoint node_b: '{seg.node_b}'"
                )

            segments_map[seg.id] = seg
            segment_to_edge[seg.id] = (seg.node_a, seg.node_b)
            edge_to_segment[(seg.node_a, seg.node_b)] = seg.id
            edge_to_segment[(seg.node_b, seg.node_a)] = seg.id

            # Serialise geometry coordinates for attributes
            centerline_coords = [(p.x, p.y) for p in seg.centerline]
            polygon_coords = [(p.x, p.y) for p in seg.polygon]

            G.add_edge(
                seg.node_a,
                seg.node_b,
                segment_id=seg.id,
                length_m=float(seg.length_m),
                width_px=float(seg.width_px),
                zone=seg.zone.value if hasattr(seg.zone, "value") else str(seg.zone),
                centerline=centerline_coords,
                polygon=polygon_coords,
            )

        return cls(
            scene_id=scene.scene_id,
            graph=G,
            intersections=intersections_map,
            segments=segments_map,
            segment_to_edge=segment_to_edge,
            edge_to_segment=edge_to_segment,
        )

    @classmethod
    def from_json(cls, json_source: str | Path | dict[str, Any]) -> RoadGraph:
        """
        Loads and validates a RoadGraph from a JSON file path, JSON string, or dict.
        """
        if isinstance(json_source, Path):
            with open(json_source, "r", encoding="utf-8") as f:
                scene = Scene.model_validate_json(f.read())
        elif isinstance(json_source, str):
            stripped = json_source.strip()
            if stripped.startswith("{"):
                scene = Scene.model_validate_json(stripped)
            else:
                path_obj = Path(stripped)
                if path_obj.exists():
                    with open(path_obj, "r", encoding="utf-8") as f:
                        scene = Scene.model_validate_json(f.read())
                else:
                    scene = Scene.model_validate_json(stripped)
        elif isinstance(json_source, dict):
            scene = Scene.model_validate(json_source)
        else:
            raise TypeError(f"Unsupported json_source type: {type(json_source)}")

        return cls.from_scene(scene)

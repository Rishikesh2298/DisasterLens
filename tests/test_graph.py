"""
Unit tests for DisasterLens road graph construction.
"""

from __future__ import annotations

import copy
from pathlib import Path

import networkx as nx
import pytest

from dl.contracts.scene import Scene
from dl.routing.graph import RoadGraph

DEMO_SCENE_PATH = Path(__file__).parent.parent / "scenarios" / "demo_city" / "scene.json"


@pytest.fixture
def demo_scene() -> Scene:
    with open(DEMO_SCENE_PATH, "r", encoding="utf-8") as f:
        return Scene.model_validate_json(f.read())


class TestRoadGraph:
    """Tests 1–5: Road graph structure, attributes, validation, and error handling."""

    def test_01_demo_graph_node_and_edge_counts(self, demo_scene: Scene):
        """Requirement 1: Demo graph has 36 nodes and 60 edges."""
        road_graph = RoadGraph.from_scene(demo_scene)
        assert road_graph.node_count == 36
        assert road_graph.edge_count == 60
        assert road_graph.graph.number_of_nodes() == 36
        assert road_graph.graph.number_of_edges() == 60

    def test_02_all_demo_nodes_are_connected(self, demo_scene: Scene):
        """Requirement 2: All demo nodes are connected (single component)."""
        road_graph = RoadGraph.from_scene(demo_scene)
        assert road_graph.is_connected is True
        assert road_graph.validate_connectivity() is True
        assert nx.is_connected(road_graph.graph) is True

    def test_03_edge_attributes_are_preserved(self, demo_scene: Scene):
        """Requirement 3: Edge attributes are preserved (segment_id, length_m, geometry, zone)."""
        road_graph = RoadGraph.from_scene(demo_scene)

        # Inspect SEG-001 (N1 <-> N2)
        edge_data = road_graph.graph.get_edge_data("N1", "N2")
        assert edge_data is not None
        assert edge_data["segment_id"] == "SEG-001"
        assert abs(edge_data["length_m"] - 34.56) < 1e-3
        assert edge_data["zone"] == "NW"
        assert len(edge_data["centerline"]) == 2
        assert len(edge_data["polygon"]) == 4

        # Verify mapping consistency
        assert road_graph.get_edge_for_segment("SEG-001") == ("N1", "N2")
        assert road_graph.get_segment_for_edge("N1", "N2") == "SEG-001"
        assert road_graph.get_segment_for_edge("N2", "N1") == "SEG-001"

    def test_04_missing_endpoint_rejection(self, demo_scene: Scene):
        """Requirement 4: Missing edge endpoints must be rejected with ValueError."""
        corrupted_scene_data = demo_scene.model_dump()
        # Add a road segment pointing to non-existent nodes
        bad_segment = {
            "id": "SEG-999",
            "node_a": "N99",  # missing
            "node_b": "N2",
            "centerline": [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 10.0}],
            "polygon": [
                {"x": 0.0, "y": 0.0},
                {"x": 10.0, "y": 0.0},
                {"x": 10.0, "y": 10.0},
                {"x": 0.0, "y": 10.0},
            ],
            "length_m": 25.0,
            "width_px": 40.0,
            "zone": "NW",
        }
        corrupted_scene_data["road_segments"].append(bad_segment)
        corrupted_scene = Scene.model_validate(corrupted_scene_data)

        with pytest.raises(ValueError, match="missing endpoint node_a"):
            RoadGraph.from_scene(corrupted_scene)

    def test_05_duplicate_id_rejection(self, demo_scene: Scene):
        """Requirement 5: Duplicate node IDs and segment IDs must be rejected."""
        # 5a. Duplicate intersection ID
        scene_dup_node = demo_scene.model_dump()
        dup_node = copy.deepcopy(scene_dup_node["intersections"][0])
        scene_dup_node["intersections"].append(dup_node)
        with pytest.raises(ValueError, match="Duplicate intersection ID"):
            RoadGraph.from_scene(Scene.model_validate(scene_dup_node))

        # 5b. Duplicate segment ID
        scene_dup_seg = demo_scene.model_dump()
        dup_seg = copy.deepcopy(scene_dup_seg["road_segments"][0])
        scene_dup_seg["road_segments"].append(dup_seg)
        with pytest.raises(ValueError, match="Duplicate road segment ID"):
            RoadGraph.from_scene(Scene.model_validate(scene_dup_seg))

    def test_load_from_json_file_and_string(self):
        """Verifies loading directly from file path and JSON string."""
        road_graph_file = RoadGraph.from_json(DEMO_SCENE_PATH)
        assert road_graph_file.node_count == 36

        with open(DEMO_SCENE_PATH, "r", encoding="utf-8") as f:
            raw_str = f.read()
        road_graph_str = RoadGraph.from_json(raw_str)
        assert road_graph_str.node_count == 36

    def test_06_edge_lookup_errors(self, demo_scene: Scene):
        """KeyError when segment or edge does not exist."""
        road_graph = RoadGraph.from_scene(demo_scene)
        with pytest.raises(KeyError, match="Segment 'SEG-NONEXISTENT' not found"):
            road_graph.get_edge_for_segment("SEG-NONEXISTENT")
        with pytest.raises(KeyError, match="No segment found connecting edge"):
            road_graph.get_segment_for_edge("N1", "N99")

    def test_07_from_json_dict_and_invalid_type(self, demo_scene: Scene):
        """from_json supports dict and rejects invalid types."""
        d = demo_scene.model_dump()
        rg = RoadGraph.from_json(d)
        assert rg.node_count == 36
        with pytest.raises(TypeError, match="Unsupported json_source type"):
            RoadGraph.from_json(12345)  # type: ignore

    def test_08_disconnected_graph_and_empty_graph(self):
        """Test is_connected and validate_connectivity on disconnected and empty graphs."""
        empty_rg = RoadGraph(
            scene_id="empty",
            graph=nx.Graph(),
            intersections={},
            segments={},
            segment_to_edge={},
            edge_to_segment={},
        )
        assert empty_rg.node_count == 0
        assert empty_rg.edge_count == 0
        assert empty_rg.is_connected is True
        assert empty_rg.validate_connectivity() is True

        # Disconnected 2-node graph
        g_disc = nx.Graph()
        g_disc.add_node("A")
        g_disc.add_node("B")
        disc_rg = RoadGraph(
            scene_id="disc",
            graph=g_disc,
            intersections={},
            segments={},
            segment_to_edge={},
            edge_to_segment={},
        )
        assert disc_rg.is_connected is False
        assert disc_rg.validate_connectivity() is False

    def test_09_missing_endpoint_node_b(self, demo_scene: Scene):
        """Missing endpoint node_b must raise ValueError."""
        data = demo_scene.model_dump()
        bad_seg = {
            "id": "SEG-998",
            "node_a": "N1",
            "node_b": "N99",  # missing
            "centerline": [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 10.0}],
            "polygon": [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}, {"x": 0.0, "y": 10.0}],
            "length_m": 25.0,
            "width_px": 40.0,
            "zone": "NW",
        }
        data["road_segments"].append(bad_seg)
        with pytest.raises(ValueError, match="missing endpoint node_b"):
            RoadGraph.from_scene(Scene.model_validate(data))

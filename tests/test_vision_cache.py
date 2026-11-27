"""
tests/test_vision_cache.py
--------------------------
Unit tests for dl/vision/cache.py.

All tests use a temporary directory for cache storage so they never
touch results/cache/ on disk and are fully isolated from each other.

No external API calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dl.contracts.enums import Difficulty, RoadStatus, Verdict, HazardType
from dl.contracts.scene import Box, GroundTruth, RoadNode, RoadSegment, Scene
from dl.contracts.vision import PredictedHazard, SceneAnalysis, SegmentVerdict
from dl.vision.base import ZoneComparisonResult
from dl.vision.cache import CacheStore, CachedVisionAdapter, compute_cache_key


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_cache_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory for each test."""
    d = tmp_path / "cache"
    d.mkdir()
    return d


def _make_scene(scene_id: str = "S-TEST") -> Scene:
    """Return a minimal valid Scene object (no ground-truth look-up needed)."""
    return Scene(
        scene_id=scene_id,
        difficulty=Difficulty.EASY,
        split="dev",
        seed=0,
        image_width=512,
        image_height=512,
        nodes=[
            RoadNode(node_id="N1", x=0.0, y=0.0),
            RoadNode(node_id="N2", x=100.0, y=0.0),
        ],
        segments=[
            RoadSegment(
                segment_id="R1",
                from_node="N1",
                to_node="N2",
                length=100.0,
                centerline=[(0.0, 0.0), (100.0, 0.0)],
                polygon=[],
            )
        ],
        hazards=[],
        ground_truth=GroundTruth(
            hazards=[],
            segment_status={},
            damaged_building_count=0,
            water_regions=[],
            route_questions={},
            zone_comparisons={},
        ),
    )


def _make_analysis(scene_id: str = "S-TEST", model_id: str = "test-model") -> SceneAnalysis:
    """Return a minimal valid SceneAnalysis."""
    return SceneAnalysis(
        scene_id=scene_id,
        hazards=[
            PredictedHazard(
                type=HazardType.FLOOD,
                bbox=Box((10.0, 10.0, 50.0, 50.0)),
                confidence=0.9,
            )
        ],
        segment_verdicts={
            "R1": SegmentVerdict(
                status=RoadStatus.CLEAR,
                confidence=0.75,
                evidence="No obstruction detected.",
                visible=True,
            )
        },
        damaged_building_count=0,
        water_regions=[],
        image_quality_good=True,
        model_id=model_id,
        prompt_version="v1",
        valid_json=True,
        latency_ms=120,
    )


def _make_inner_adapter(analysis: SceneAnalysis) -> MagicMock:
    """Return a mock VisionAdapter that returns the given analysis once."""
    adapter = MagicMock()
    adapter.model_id = analysis.model_id
    adapter.analyze_scene.return_value = analysis
    return adapter


# ---------------------------------------------------------------------------
# 1. compute_cache_key – determinism and sensitivity
# ---------------------------------------------------------------------------

class TestComputeCacheKey:
    """Verify cache-key computation properties."""

    def test_same_inputs_same_key(self):
        """Identical inputs must produce identical keys."""
        key1 = compute_cache_key("model-a", "prompt text", b"\x00\x01\x02")
        key2 = compute_cache_key("model-a", "prompt text", b"\x00\x01\x02")
        assert key1 == key2

    def test_key_is_64_char_hex(self):
        """The key must be a 64-character lowercase hexadecimal string (SHA-256)."""
        key = compute_cache_key("m", "p", b"i")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_different_model_different_key(self):
        """Changing only the model must change the key."""
        key1 = compute_cache_key("model-a", "prompt", b"image")
        key2 = compute_cache_key("model-b", "prompt", b"image")
        assert key1 != key2

    def test_different_prompt_different_key(self):
        """Changing only the prompt must change the key."""
        key1 = compute_cache_key("model", "prompt-A", b"image")
        key2 = compute_cache_key("model", "prompt-B", b"image")
        assert key1 != key2

    def test_different_image_different_key(self):
        """Changing only the image bytes must change the key."""
        key1 = compute_cache_key("model", "prompt", b"imageA")
        key2 = compute_cache_key("model", "prompt", b"imageB")
        assert key1 != key2

    def test_no_concatenation_collision(self):
        """
        Separator prevents 'ab'+'c' == 'a'+'bc' collisions.
        E.g. ("ab", "c", b"") must differ from ("a", "bc", b"").
        """
        key1 = compute_cache_key("ab", "c", b"")
        key2 = compute_cache_key("a", "bc", b"")
        assert key1 != key2


# ---------------------------------------------------------------------------
# 2. CacheStore – low-level read / write
# ---------------------------------------------------------------------------

class TestCacheStore:
    """Test the filesystem key→JSON store directly."""

    def test_miss_when_empty(self, tmp_cache_dir: Path):
        store = CacheStore(cache_dir=tmp_cache_dir)
        assert store.get("nonexistent") is None

    def test_put_and_get_roundtrip(self, tmp_cache_dir: Path):
        store = CacheStore(cache_dir=tmp_cache_dir)
        payload = {"scene_id": "S-TEST", "model_id": "m", "value": 42}
        store.put("abc123", payload)
        retrieved = store.get("abc123")
        assert retrieved == payload

    def test_exists_true_after_put(self, tmp_cache_dir: Path):
        store = CacheStore(cache_dir=tmp_cache_dir)
        store.put("key1", {"x": 1})
        assert store.exists("key1") is True

    def test_exists_false_before_put(self, tmp_cache_dir: Path):
        store = CacheStore(cache_dir=tmp_cache_dir)
        assert store.exists("key_missing") is False

    def test_corrupted_file_returns_none(self, tmp_cache_dir: Path):
        """A corrupted (non-JSON) cache file must be treated as a miss, not an error."""
        store = CacheStore(cache_dir=tmp_cache_dir)
        (tmp_cache_dir / "badkey.json").write_text("NOT_JSON{{{", encoding="utf-8")
        result = store.get("badkey")
        assert result is None

    def test_non_dict_json_returns_none(self, tmp_cache_dir: Path):
        """A JSON file containing a list (not an object) must be treated as a miss."""
        store = CacheStore(cache_dir=tmp_cache_dir)
        (tmp_cache_dir / "listkey.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = store.get("listkey")
        assert result is None

    def test_put_creates_parent_dir(self, tmp_path: Path):
        """CacheStore.put should create the cache directory if it does not exist."""
        new_dir = tmp_path / "deep" / "nested" / "cache"
        assert not new_dir.exists()
        store = CacheStore(cache_dir=new_dir)
        store.put("k", {"a": 1})
        assert (new_dir / "k.json").exists()


# ---------------------------------------------------------------------------
# 3. CachedVisionAdapter – end-to-end behaviour
# ---------------------------------------------------------------------------

class TestCachedVisionAdapter:
    """Integration tests for CachedVisionAdapter."""

    def test_cache_miss_calls_inner_adapter(self, tmp_cache_dir: Path):
        """On a cold cache the inner adapter must be called exactly once."""
        analysis = _make_analysis()
        inner = _make_inner_adapter(analysis)
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()

        result = adapter.analyze_scene(image_bytes=b"fake-image", scene=scene)

        inner.analyze_scene.assert_called_once()
        assert result.scene_id == analysis.scene_id

    def test_cache_miss_writes_file(self, tmp_cache_dir: Path):
        """After a cache miss the response must be persisted to disk."""
        analysis = _make_analysis()
        inner = _make_inner_adapter(analysis)
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()

        adapter.analyze_scene(image_bytes=b"fake-image", scene=scene)

        files = list(tmp_cache_dir.glob("*.json"))
        assert len(files) == 1, "Expected exactly one cache file on disk after a miss."

    def test_cache_hit_does_not_call_inner_adapter(self, tmp_cache_dir: Path):
        """On a warm cache the inner adapter must NOT be called."""
        analysis = _make_analysis()
        inner = _make_inner_adapter(analysis)
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()
        image = b"fake-image"

        # First call → miss → store
        adapter.analyze_scene(image_bytes=image, scene=scene)
        # Second call → hit
        result = adapter.analyze_scene(image_bytes=image, scene=scene)

        assert inner.analyze_scene.call_count == 1, "Inner adapter must be called only once."
        assert result.scene_id == analysis.scene_id

    def test_hit_returns_equivalent_analysis(self, tmp_cache_dir: Path):
        """The analysis returned from the cache must match the originally stored result."""
        analysis = _make_analysis()
        inner = _make_inner_adapter(analysis)
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()
        image = b"fake-image"

        first = adapter.analyze_scene(image_bytes=image, scene=scene)
        second = adapter.analyze_scene(image_bytes=image, scene=scene)

        assert first.model_dump() == second.model_dump()

    def test_different_image_different_cache_entry(self, tmp_cache_dir: Path):
        """Two calls with different images must each produce their own cache file."""
        analysis_a = _make_analysis(model_id="m")
        analysis_b = _make_analysis(model_id="m")
        inner = MagicMock()
        inner.model_id = "m"
        inner.analyze_scene.side_effect = [analysis_a, analysis_b]

        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()

        adapter.analyze_scene(image_bytes=b"imageA", scene=scene)
        adapter.analyze_scene(image_bytes=b"imageB", scene=scene)

        # Both were misses → two separate cache files
        files = list(tmp_cache_dir.glob("*.json"))
        assert len(files) == 2
        assert inner.analyze_scene.call_count == 2

    def test_different_prompt_version_different_cache_entry(self, tmp_cache_dir: Path):
        """Two calls with different prompt versions must NOT share a cache entry."""
        analysis = _make_analysis()
        inner = MagicMock()
        inner.model_id = analysis.model_id
        inner.analyze_scene.return_value = analysis

        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()
        image = b"img"

        adapter.analyze_scene(image_bytes=image, scene=scene, prompt_version="v1")
        adapter.analyze_scene(image_bytes=image, scene=scene, prompt_version="v2")

        # Two distinct misses → two files, inner called twice
        assert inner.analyze_scene.call_count == 2
        files = list(tmp_cache_dir.glob("*.json"))
        assert len(files) == 2

    def test_corrupted_cache_falls_through_to_inner(self, tmp_cache_dir: Path):
        """A corrupted cache file must trigger a miss and call the inner adapter."""
        analysis = _make_analysis()
        inner = _make_inner_adapter(analysis)
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()
        image = b"img"

        # Compute the key the adapter will use and plant a corrupted file
        from dl.vision.cache import compute_cache_key
        key = compute_cache_key(
            model_id=inner.model_id,
            prompt_content=f"prompt_version=v1|scene_id={scene.scene_id}",
            image_bytes=image,
        )
        (tmp_cache_dir / f"{key}.json").write_text("CORRUPTED{{{", encoding="utf-8")

        result = adapter.analyze_scene(image_bytes=image, scene=scene)

        inner.analyze_scene.assert_called_once()
        assert result.scene_id == analysis.scene_id

    def test_no_credentials_in_cache_file(self, tmp_cache_dir: Path):
        """Cache files must not contain the string 'api_key' or 'GEMINI_API_KEY'."""
        analysis = _make_analysis()
        inner = _make_inner_adapter(analysis)
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()

        adapter.analyze_scene(image_bytes=b"img", scene=scene)

        for cache_file in tmp_cache_dir.glob("*.json"):
            contents = cache_file.read_text(encoding="utf-8")
            assert "api_key" not in contents.lower()
            assert "GEMINI_API_KEY" not in contents

    def test_answer_route_questions_delegates_to_inner(self, tmp_cache_dir: Path):
        """answer_route_questions must always delegate; no caching."""
        inner = MagicMock()
        inner.model_id = "m"
        inner.answer_route_questions.return_value = {"Q-01": Verdict.CLEAR}
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()

        result = adapter.answer_route_questions(
            image_bytes=b"img",
            questions={"Q-01": "Is route blocked?"},
            scene=scene,
        )

        inner.answer_route_questions.assert_called_once()
        assert result == {"Q-01": Verdict.CLEAR}

    def test_compare_zones_delegates_to_inner(self, tmp_cache_dir: Path):
        """compare_zones must always delegate; no caching."""
        inner = MagicMock()
        inner.model_id = "m"
        inner.compare_zones.return_value = "zone_a"
        adapter = CachedVisionAdapter(inner_adapter=inner, cache_dir=tmp_cache_dir)
        scene = _make_scene()
        box = Box((0.0, 0.0, 10.0, 10.0))

        result = adapter.compare_zones(
            image_bytes=b"img",
            zone_a=box,
            zone_b=box,
            scene=scene,
        )

        inner.compare_zones.assert_called_once()
        assert result == "zone_a"

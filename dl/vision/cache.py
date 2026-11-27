"""
dl/vision/cache.py
------------------
SHA-256 response caching for VisionAdapter.

Design
------
* CachedVisionAdapter wraps any inner VisionAdapter.
* The cache key is the hex SHA-256 digest of:
      model_id | prompt_content | image_bytes
  concatenated with a NUL byte separator so that
  "ab" + "c" != "a" + "bc".
* Raw responses are stored as JSON files inside `results/cache/`
  (configurable via `cache_dir`).
* Only SceneAnalysis responses from `analyze_scene` are cached.
  `answer_route_questions` and `compare_zones` are always delegated
  to the inner adapter without caching (they return lighter objects
  whose caching would need separate contracts).

No API keys or credentials are ever written to cache files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from dl.contracts.enums import Verdict
from dl.contracts.scene import Box, Scene
from dl.contracts.vision import SceneAnalysis
from dl.vision.base import VisionAdapter, ZoneComparisonResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default cache directory – relative to the repository root.
# When running from C:\Disaster\DisasterLens this resolves to
#   C:\Disaster\DisasterLens\results\cache\
# ---------------------------------------------------------------------------
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "results" / "cache"


# ---------------------------------------------------------------------------
# Public helper: cache-key computation
# ---------------------------------------------------------------------------

def compute_cache_key(
    model_id: str,
    prompt_content: str,
    image_bytes: bytes,
) -> str:
    """
    Return a 64-character hex SHA-256 cache key.

    The key depends on:
    - model_id      – changing the model produces a different key.
    - prompt_content – changing the prompt produces a different key.
    - image_bytes   – changing the image produces a different key.

    A NUL-byte (``\\x00``) separator between each component prevents
    concatenation collisions (e.g. ``"ab"+"c"`` ≠ ``"a"+"bc"``).

    Args:
        model_id: Identifier of the vision model (e.g. ``"gemini-3.8-flash"``).
        prompt_content: Full prompt text sent to the model.
        image_bytes: Raw binary content of the scene image.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest.
    """
    sep = b"\x00"
    payload = (
        model_id.encode("utf-8")
        + sep
        + prompt_content.encode("utf-8")
        + sep
        + image_bytes
    )
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Public helper: low-level cache read / write
# ---------------------------------------------------------------------------

class CacheStore:
    """
    Thin filesystem key→JSON store backed by ``results/cache/``.

    Each entry is stored as ``<cache_dir>/<key>.json``.
    The store never raises on read failures (corrupted or missing
    files are treated as cache misses).  Write failures are logged
    as warnings and re-raised so the caller can decide.

    Args:
        cache_dir: Directory in which cache files are stored.
                   Created automatically on first write.
    """

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self._dir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, key: str) -> dict[str, Any] | None:
        """
        Load a cached JSON payload.

        Returns:
            Parsed dict on cache hit, ``None`` on miss or corruption.
        """
        path = self._path_for(key)
        if not path.exists():
            logger.debug("Cache miss – file not found: %s", path.name)
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Root JSON must be an object.")
            logger.debug("Cache hit: %s", path.name)
            return data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Cache file %s is unreadable or corrupted (%s). Treating as miss.",
                path.name,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def put(self, key: str, data: dict[str, Any]) -> Path:
        """
        Persist a JSON payload to the cache.

        Args:
            key: SHA-256 hex string from :func:`compute_cache_key`.
            data: Serialisable dict (the ``SceneAnalysis.model_dump()``).

        Returns:
            Path of the written file.

        Raises:
            OSError: If the file cannot be written.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(key)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("Cached response written: %s", path.name)
        return path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path_for(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def exists(self, key: str) -> bool:
        """Return True if a cache file for *key* exists on disk."""
        return self._path_for(key).exists()


# ---------------------------------------------------------------------------
# CachedVisionAdapter
# ---------------------------------------------------------------------------

class CachedVisionAdapter(VisionAdapter):
    """
    Transparent caching wrapper around any :class:`~dl.vision.base.VisionAdapter`.

    On ``analyze_scene``:

    1. Compute a SHA-256 cache key from (model_id, prompt_content, image_bytes).
    2. If a valid cache file exists → deserialise and return without calling the
       inner adapter (cache *hit*).
    3. Otherwise call the inner adapter, serialise the result, persist it, and
       return it (cache *miss* → stored for future hits).

    ``answer_route_questions`` and ``compare_zones`` are always delegated to the
    inner adapter; their responses are not cached by this layer.

    Args:
        inner_adapter: Any configured VisionAdapter (live, mock, …).
        cache_dir: Override the default ``results/cache/`` storage location.
        prompt_version: Default prompt version forwarded to the inner adapter.
    """

    def __init__(
        self,
        inner_adapter: VisionAdapter,
        cache_dir: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        self._inner = inner_adapter
        self._store = CacheStore(cache_dir=cache_dir)

    # ------------------------------------------------------------------
    # VisionAdapter interface
    # ------------------------------------------------------------------

    def analyze_scene(
        self,
        image_bytes: bytes,
        scene: Scene,
        prompt_version: str = "v1",
    ) -> SceneAnalysis:
        """
        Return a cached SceneAnalysis when available, otherwise delegate to
        the inner adapter and cache the fresh result.

        IMPORTANT: ``scene.ground_truth`` is never written to cache files.
        Only the ``SceneAnalysis`` Pydantic model dump (which contains only
        the model's predictions) is stored.
        """
        # Build a stable string representation of the prompt.
        # We include prompt_version + scene_id so that:
        #   - Different scenes always produce different keys.
        #   - Different prompt versions always produce different keys.
        # The actual prompt text is provided by the inner adapter; we
        # approximate it here using the metadata that determines which
        # prompt file is selected.  This is correct for all current
        # providers.  If a future provider builds prompts dynamically,
        # it should override or extend the cache key.
        prompt_repr = f"prompt_version={prompt_version}|scene_id={scene.scene_id}"
        model_id = getattr(self._inner, "model_id", "") or ""
        key = compute_cache_key(
            model_id=model_id,
            prompt_content=prompt_repr,
            image_bytes=image_bytes,
        )

        # --- Cache hit ---
        cached = self._store.get(key)
        if cached is not None:
            try:
                analysis = SceneAnalysis.model_validate(cached)
                logger.info(
                    "analyze_scene – cache HIT for scene '%s' (key %.12s…)",
                    scene.scene_id,
                    key,
                )
                return analysis
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Cached payload for key %.12s… failed validation (%s). "
                    "Falling through to inner adapter.",
                    key,
                    exc,
                )

        # --- Cache miss – delegate to inner adapter ---
        logger.info(
            "analyze_scene – cache MISS for scene '%s' (key %.12s…). "
            "Calling inner adapter.",
            scene.scene_id,
            key,
        )
        result: SceneAnalysis = self._inner.analyze_scene(
            image_bytes=image_bytes,
            scene=scene,
            prompt_version=prompt_version,
        )

        # Persist only the model's predictions – never ground truth or credentials.
        try:
            self._store.put(key, result.model_dump())
        except OSError as exc:
            logger.warning(
                "Failed to write cache file for key %.12s…: %s",
                key,
                exc,
            )

        return result

    def answer_route_questions(
        self,
        image_bytes: bytes,
        questions: dict[str, str],
        scene: Scene,
        prompt_version: str = "v1",
    ) -> dict[str, Verdict]:
        """Delegate unconditionally; route-question responses are not cached."""
        return self._inner.answer_route_questions(
            image_bytes=image_bytes,
            questions=questions,
            scene=scene,
            prompt_version=prompt_version,
        )

    def compare_zones(
        self,
        image_bytes: bytes,
        zone_a: Box,
        zone_b: Box,
        scene: Scene,
        comparison_id: str = "",
        prompt_version: str = "v1",
    ) -> ZoneComparisonResult:
        """Delegate unconditionally; zone-comparison responses are not cached."""
        return self._inner.compare_zones(
            image_bytes=image_bytes,
            zone_a=zone_a,
            zone_b=zone_b,
            scene=scene,
            comparison_id=comparison_id,
            prompt_version=prompt_version,
        )

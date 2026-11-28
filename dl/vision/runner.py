"""
dl/vision/runner.py
-------------------
Batch runner for the DisasterLens Vision AI engine.

Usage (CLI)
-----------
    python -m dl.vision.runner [OPTIONS]

Options
-------
    --dataset DIR       Dataset root directory (default: datasets/v1)
    --split SPLIT       Dataset split to process: dev or test (default: dev)
    --model MODEL       Model/adapter name (default: mock)
    --prompt-version V  Prompt version string (default: v1)
    --image-variant V   Image variant: plain or labelled (default: plain)
    --output DIR        Output directory for predictions and run log
                        (default: results/predictions/<split>)
    --workers N         Worker pool size, 1–8 (default: 3)
    --no-cache          Disable CachedVisionAdapter wrapping (use raw adapter)

What the runner does
--------------------
1.  Discovers all scene folders under <dataset>/<scene_id>/ whose split
    matches the requested split (falling back to treating all scenes as
    'dev' when split is absent from raw files).
2.  Loads each scene.json + ground_truth.json into a contract-valid Scene
    object via the internal SceneLoader.
3.  Loads the matching image file (image_plain.png or image_labelled.png).
4.  Loads questions.json for route-question answering.
5.  Calls adapter.analyze_scene() and adapter.answer_route_questions().
6.  Writes one contract-valid SceneAnalysis JSON per scene.
7.  Writes a run-log JSON with per-scene status, latency and validity.
8.  Skips scenes whose output already exists (resume support).
9.  Applies exponential back-off on transient failures (up to 3 retries).
10. Stops cleanly on quota / auth errors with a clear message.

Dataset schema mismatch (documented blocker)
--------------------------------------------
The on-disk scene.json uses a different schema than the Scene Pydantic
contract (dl.contracts.scene.Scene):

  Raw field          → Contract field
  ─────────────────────────────────────
  road_segments      → segments
  intersections      → nodes
  segment.id         → segment_id
  segment.node_a/b   → from_node / to_node
  segment.length_m   → length
  intersection.id    → node_id
  hazard.id          → hazard_id
  hazard bbox dict   → Box(x1,y1,x2,y2)
  hazard polygon     → list[(x,y)]
  (no split field)   → inferred from --split arg
  (no ground_truth)  → loaded from ground_truth.json

ground_truth.json also differs from GroundTruth:

  Raw field                       → Contract field
  ──────────────────────────────────────────────────
  segment_statuses[].status       → lowercase (CLEAR→clear)
  segment_statuses[].segment_id   → dict key
  damaged_building_ids (list)     → damaged_building_count (int)

The SceneLoader class inside this module bridges both gaps without
modifying any shared contract.

CachedVisionAdapter compatibility
----------------------------------
CachedVisionAdapter wraps any VisionAdapter and is compatible with the
runner's adapter interface.  When --no-cache is NOT passed, the runner
wraps the resolved adapter in CachedVisionAdapter using the output
directory as the cache directory.  This means cache files land alongside
the prediction files, which is intentional for replay-based pipelines.

The registry's 'cached' mode is NOT used here because it requires a
pre-registered live provider; instead the runner instantiates the cache
layer directly so it also works in mock/baseline mode.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dl.contracts.enums import HazardType
from dl.contracts.scene import (
    Box,
    GroundTruth,
    Hazard,
    RoadNode,
    RoadSegment,
    Scene,
)
from dl.contracts.vision import SceneAnalysis
from dl.vision.base import VisionAdapter
from dl.vision.registry import get_adapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATASET_DIR = Path("datasets") / "v1"
DEFAULT_OUTPUT_DIR = Path("results") / "predictions"
MIN_WORKERS = 1
MAX_WORKERS = 8
DEFAULT_WORKERS = 3

# Exponential back-off settings for transient errors
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.0  # seconds

# Errors whose string representation suggests quota / auth failure.
# On these the runner stops immediately (no retry).
_QUOTA_KEYWORDS = frozenset({
    "quota",
    "rateLimitExceeded",
    "RESOURCE_EXHAUSTED",
    "403",
    "401",
    "UNAUTHENTICATED",
    "API_KEY_INVALID",
})


# ---------------------------------------------------------------------------
# Dataclasses for the run log
# ---------------------------------------------------------------------------

@dataclass
class SceneResult:
    """Per-scene entry in the run log."""
    scene_id: str
    status: str           # "ok" | "skipped" | "failed" | "quota_stop"
    latency_ms: int | None = None
    valid_json: bool | None = None
    error: str | None = None


@dataclass
class RunLog:
    """Full run log written at the end of a batch run."""
    run_id: str
    model: str
    prompt_version: str
    image_variant: str
    split: str
    dataset_dir: str
    output_dir: str
    started_at: str
    finished_at: str = ""
    total_scenes: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    scenes: list[SceneResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Dataset loader — bridges raw file format → contract objects
# ---------------------------------------------------------------------------

def _haz_type(raw: str) -> HazardType:
    """Map raw hazard type strings to HazardType enum (case-insensitive)."""
    mapping = {
        "flood": HazardType.FLOOD,
        "debris": HazardType.DEBRIS,
        "fallen_tree": HazardType.FALLEN_TREE,
        "road_damage": HazardType.ROAD_DAMAGE,
        "damaged_building": HazardType.DAMAGED_BUILDING,
    }
    return mapping.get(raw.lower().strip(), HazardType.DEBRIS)


def _bbox_dict_to_box(b: dict[str, float]) -> Box:
    """
    Convert a raw bbox dict ``{x_min, y_min, x_max, y_max}`` to a Box.
    Handles both {x_min/x_max/y_min/y_max} and {x1/y1/x2/y2} forms.
    """
    if "x_min" in b:
        return Box((b["x_min"], b["y_min"], b["x_max"], b["y_max"]))
    return Box((b["x1"], b["y1"], b["x2"], b["y2"]))


def _xy_list_to_tuples(pts: list[dict]) -> list[tuple[float, float]]:
    """Convert a list of ``{x, y}`` dicts to a list of (x, y) tuples."""
    return [(p["x"], p["y"]) for p in pts]


class SceneLoader:
    """
    Loads a single DisasterLens scene from its on-disk folder.

    The on-disk layout per scene::

        <dataset_root>/<scene_id>/
            scene.json          # raw scene geometry (non-contract format)
            ground_truth.json   # ground-truth statuses (non-contract format)
            image_plain.png
            image_labelled.png
            questions.json

    Returns contract-valid objects: ``Scene``, image bytes, and question dict.

    Args:
        scene_dir: Path to the scene folder (e.g. ``datasets/v1/S-0001``).
        split: The dataset split to inject (``"dev"`` or ``"test"``).
               The raw scene.json does not contain a split field.
    """

    def __init__(self, scene_dir: Path, split: str = "dev") -> None:
        self.scene_dir = scene_dir
        self.split = split
        self.scene_id = scene_dir.name

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def load_scene(self) -> Scene:
        """Parse and return a contract-valid Scene."""
        raw = json.loads((self.scene_dir / "scene.json").read_bytes())
        gt_raw = json.loads((self.scene_dir / "ground_truth.json").read_bytes())
        return self._build_scene(raw, gt_raw)

    def load_image(self, variant: str = "plain") -> bytes:
        """
        Return raw image bytes.

        Args:
            variant: ``"plain"`` or ``"labelled"``.

        Raises:
            FileNotFoundError: If the image file is missing.
        """
        filename = f"image_{variant}.png"
        path = self.scene_dir / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Image file not found: {path}. "
                f"Available files: {[f.name for f in self.scene_dir.iterdir()]}"
            )
        return path.read_bytes()

    def load_questions(self) -> dict[str, str]:
        """
        Return a ``{question_id: prompt_text}`` mapping from questions.json.

        Only questions of type ``route_obstruction_*`` are included, as those
        map to ``answer_route_questions()`` which returns ``Verdict`` values.
        """
        raw = json.loads((self.scene_dir / "questions.json").read_bytes())
        result: dict[str, str] = {}
        for q in raw.get("questions", []):
            if "route_obstruction" in q.get("type", ""):
                result[q["id"]] = q["prompt"]
        return result

    # ------------------------------------------------------------------
    # Private builders
    # ------------------------------------------------------------------

    def _build_scene(self, raw: dict, gt_raw: dict) -> Scene:
        """Translate raw dicts into a contract-valid Scene object."""
        nodes = self._build_nodes(raw.get("intersections", []))
        segments = self._build_segments(raw.get("road_segments", []))
        hazards = self._build_hazards(raw.get("hazards", []))
        ground_truth = self._build_ground_truth(gt_raw)

        return Scene(
            scene_id=self.scene_id,
            difficulty=raw.get("difficulty", "easy").lower(),
            split=self.split,
            seed=raw.get("seed", 0),
            image_width=raw.get("image_width", 512),
            image_height=raw.get("image_height", 512),
            nodes=nodes,
            segments=segments,
            hazards=hazards,
            ground_truth=ground_truth,
        )

    @staticmethod
    def _build_nodes(raw_nodes: list[dict]) -> list[RoadNode]:
        """Translate ``intersections`` list → ``RoadNode`` list."""
        return [
            RoadNode(
                node_id=n["id"],
                x=float(n["x"]),
                y=float(n["y"]),
            )
            for n in raw_nodes
        ]

    @staticmethod
    def _build_segments(raw_segs: list[dict]) -> list[RoadSegment]:
        """Translate ``road_segments`` list → ``RoadSegment`` list."""
        result = []
        for s in raw_segs:
            centerline = _xy_list_to_tuples(s.get("centerline", []))
            if len(centerline) < 2:
                logger.warning("Segment %s has too few centerline points; skipping.", s.get("id"))
                continue
            polygon = _xy_list_to_tuples(s.get("polygon", []))
            result.append(
                RoadSegment(
                    segment_id=s["id"],
                    from_node=s["node_a"],
                    to_node=s["node_b"],
                    length=float(s.get("length_m", 1.0)),
                    centerline=centerline,
                    polygon=polygon,
                )
            )
        return result

    @staticmethod
    def _build_hazards(raw_hazards: list[dict]) -> list[Hazard]:
        """Translate raw hazard list → ``Hazard`` list."""
        result = []
        for h in raw_hazards:
            bbox = _bbox_dict_to_box(h["bbox"])
            polygon = _xy_list_to_tuples(h.get("polygon", []))
            result.append(
                Hazard(
                    hazard_id=h["id"],
                    type=_haz_type(h.get("type", "debris")),
                    bbox=bbox,
                    polygon=polygon,
                )
            )
        return result

    @staticmethod
    def _build_ground_truth(gt_raw: dict) -> GroundTruth:
        """
        Translate ground_truth.json into a GroundTruth contract object.

        Raw format::

            {
              "segment_statuses": [
                {"segment_id": "SEG-001", "status": "CLEAR", ...},
                ...
              ],
              "damaged_building_ids": [...],
              "water_region_ids": [...],
              ...
            }

        Contract format::

            GroundTruth(
                segment_status = {"SEG-001": "clear", ...},
                damaged_building_count = N,
                water_regions = [],
                hazards = [],
                ...
            )
        """
        # Build segment_status dict with lowercase values
        segment_status: dict[str, str] = {}
        for entry in gt_raw.get("segment_statuses", []):
            sid = entry["segment_id"]
            raw_status = entry.get("status", "CLEAR").upper()
            # Map uppercase → lowercase contract values
            status_map = {"BLOCKED": "blocked", "PARTIAL": "partial", "CLEAR": "clear"}
            segment_status[sid] = status_map.get(raw_status, "clear")

        damaged_count = len(gt_raw.get("damaged_building_ids", []))

        return GroundTruth(
            hazards=[],
            segment_status=segment_status,
            damaged_building_count=damaged_count,
            water_regions=[],
            route_questions={},
            zone_comparisons={},
        )


# ---------------------------------------------------------------------------
# Scene discovery
# ---------------------------------------------------------------------------

def discover_scenes(dataset_dir: Path, split: str) -> list[Path]:
    """
    Return sorted list of scene directories from the dataset root.

    A scene directory is any direct subdirectory of ``dataset_dir``
    that contains a ``scene.json`` file.  The ``split`` filter is
    informational only (since scene.json does not embed split), so all
    scenes found are returned — the caller may filter further.

    Args:
        dataset_dir: Root of the versioned dataset (e.g. ``datasets/v1``).
        split: Requested split (``"dev"`` or ``"test"``).  Used for logging.

    Returns:
        Sorted list of scene directory paths.
    """
    if not dataset_dir.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {dataset_dir}. "
            "Pass --dataset to specify a valid path."
        )

    scenes = sorted(
        p for p in dataset_dir.iterdir()
        if p.is_dir() and (p / "scene.json").exists()
    )
    logger.info(
        "Discovered %d scene(s) in %s (split=%s).", len(scenes), dataset_dir, split
    )
    return scenes


# ---------------------------------------------------------------------------
# Prediction output helpers
# ---------------------------------------------------------------------------

def prediction_path(output_dir: Path, scene_id: str) -> Path:
    """Return the expected output path for a scene's prediction JSON."""
    return output_dir / f"{scene_id}_prediction.json"


def already_done(output_dir: Path, scene_id: str) -> bool:
    """Return True if a prediction file for this scene already exists."""
    return prediction_path(output_dir, scene_id).exists()


def save_prediction(output_dir: Path, analysis: SceneAnalysis) -> Path:
    """Serialise a SceneAnalysis to disk and return the written path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = prediction_path(output_dir, analysis.scene_id)
    path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Quota / auth error detection
# ---------------------------------------------------------------------------

def _is_quota_error(exc: Exception) -> bool:
    """Return True if the exception looks like a quota or auth failure."""
    msg = str(exc)
    return any(kw in msg for kw in _QUOTA_KEYWORDS)


# ---------------------------------------------------------------------------
# Single-scene processing
# ---------------------------------------------------------------------------

def _process_one_scene(
    scene_dir: Path,
    adapter: VisionAdapter,
    split: str,
    image_variant: str,
    prompt_version: str,
    output_dir: Path,
) -> SceneResult:
    """
    Load, analyse, and save results for a single scene.

    Returns:
        SceneResult with status "ok", "skipped", or "failed".
    """
    scene_id = scene_dir.name
    result = SceneResult(scene_id=scene_id, status="failed")

    # Resume: skip if output already exists
    if already_done(output_dir, scene_id):
        logger.info("SKIP %s — prediction already exists.", scene_id)
        result.status = "skipped"
        return result

    # Exponential back-off retry loop
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            t0 = time.monotonic()

            loader = SceneLoader(scene_dir, split=split)
            scene = loader.load_scene()
            image_bytes = loader.load_image(variant=image_variant)
            questions = loader.load_questions()

            analysis = adapter.analyze_scene(
                image_bytes=image_bytes,
                scene=scene,
                prompt_version=prompt_version,
            )

            # Route questions (best-effort; failures are non-fatal)
            if questions:
                try:
                    adapter.answer_route_questions(
                        image_bytes=image_bytes,
                        questions=questions,
                        scene=scene,
                        prompt_version=prompt_version,
                    )
                except Exception as rq_exc:
                    logger.warning("Route questions failed for %s: %s", scene_id, rq_exc)

            latency_ms = int((time.monotonic() - t0) * 1000)
            save_prediction(output_dir, analysis)

            result.status = "ok"
            result.latency_ms = latency_ms
            result.valid_json = analysis.valid_json
            logger.info("OK %s — %dms valid=%s", scene_id, latency_ms, analysis.valid_json)
            return result

        except Exception as exc:
            last_exc = exc
            if _is_quota_error(exc):
                logger.error(
                    "QUOTA/AUTH error on %s: %s. Stopping run.", scene_id, exc
                )
                result.status = "quota_stop"
                result.error = str(exc)
                return result

            backoff = _BACKOFF_BASE_S * (2 ** (attempt - 1))
            logger.warning(
                "Attempt %d/%d failed for %s: %s. Retrying in %.1fs…",
                attempt, _MAX_RETRIES, scene_id, exc, backoff,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(backoff)

    result.status = "failed"
    result.error = str(last_exc)
    logger.error("FAILED %s after %d attempts: %s", scene_id, _MAX_RETRIES, last_exc)
    return result


# ---------------------------------------------------------------------------
# Main batch run
# ---------------------------------------------------------------------------

def run_batch(
    dataset_dir: Path,
    split: str = "dev",
    model: str = "mock",
    prompt_version: str = "v1",
    image_variant: str = "plain",
    output_dir: Path | None = None,
    workers: int = DEFAULT_WORKERS,
    use_cache: bool = True,
) -> RunLog:
    """
    Run the full batch pipeline over a dataset split.

    Args:
        dataset_dir: Root of the versioned dataset (e.g. ``datasets/v1``).
        split: ``"dev"`` or ``"test"``.
        model: Adapter/model identifier (e.g. ``"mock"``,
               ``"baseline-always-clear"``).
        prompt_version: Prompt version string.
        image_variant: ``"plain"`` or ``"labelled"``.
        output_dir: Directory for prediction JSON files and run log.
        workers: Thread pool size (clamped to [1, 8]).
        use_cache: When True, wraps the adapter in CachedVisionAdapter.

    Returns:
        RunLog populated with per-scene results.
    """
    workers = max(MIN_WORKERS, min(MAX_WORKERS, workers))
    effective_output = (output_dir or (DEFAULT_OUTPUT_DIR / split)).resolve()
    effective_output.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(UTC).strftime("run_%Y%m%d_%H%M%S")
    log = RunLog(
        run_id=run_id,
        model=model,
        prompt_version=prompt_version,
        image_variant=image_variant,
        split=split,
        dataset_dir=str(dataset_dir.resolve()),
        output_dir=str(effective_output),
        started_at=datetime.now(UTC).isoformat(),
    )

    # Resolve adapter
    adapter = _build_adapter(model=model, use_cache=use_cache, output_dir=effective_output)

    # Discover scenes
    try:
        scene_dirs = discover_scenes(dataset_dir, split)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        log.finished_at = datetime.now(UTC).isoformat()
        return log

    log.total_scenes = len(scene_dirs)
    logger.info(
        "Starting run %s — %d scene(s), model=%s, workers=%d",
        run_id, len(scene_dirs), model, workers,
    )

    quota_stopped = False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_one_scene,
                sd, adapter, split, image_variant, prompt_version, effective_output,
            ): sd.name
            for sd in scene_dirs
        }

        for fut in as_completed(futures):
            scene_id = futures[fut]
            try:
                result: SceneResult = fut.result()
            except Exception as exc:
                # Unexpected executor-level error
                result = SceneResult(
                    scene_id=scene_id, status="failed", error=str(exc)
                )

            log.scenes.append(result)

            if result.status == "ok":
                log.processed += 1
            elif result.status == "skipped":
                log.skipped += 1
            elif result.status == "quota_stop":
                log.failed += 1
                quota_stopped = True
            else:
                log.failed += 1

            if quota_stopped:
                # Cancel remaining futures
                for pending_fut in futures:
                    pending_fut.cancel()
                logger.warning(
                    "Run halted due to quota/auth error. "
                    "Processed %d scene(s). Re-run to resume.",
                    log.processed,
                )
                break

    log.finished_at = datetime.now(UTC).isoformat()
    _save_run_log(effective_output, log)
    return log


def _build_adapter(model: str, use_cache: bool, output_dir: Path) -> VisionAdapter:
    """
    Instantiate the adapter for the requested model.

    Baseline strings (``"always-clear"``, ``"proximity"``,
    ``"noisy-oracle"``) are resolved directly without touching the
    registry to avoid polluting the provider registry with baselines.

    For all other model names, the registry's ``get_adapter()`` is used
    with mode=``"mock"`` as a safe default.

    If ``use_cache=True``, the resolved adapter is wrapped in
    ``CachedVisionAdapter`` using the output directory for cache storage.
    This works for mock and baseline adapters too — the cache simply
    stores their JSON outputs so identical inputs replay without calling
    the adapter again.
    """
    # Resolve baseline aliases without registry
    baseline_map = {
        "always-clear":  "AlwaysClearBaseline",
        "proximity":     "ProximityBaseline",
        "noisy-oracle":  "NoisyOracleBaseline",
        "baseline-always-clear": "AlwaysClearBaseline",
        "baseline-proximity":    "ProximityBaseline",
        "baseline-noisy-oracle": "NoisyOracleBaseline",
    }
    baseline_cls_name = baseline_map.get(model.lower())
    if baseline_cls_name:
        from dl.vision import baselines as bl_mod
        cls = getattr(bl_mod, baseline_cls_name)
        adapter: VisionAdapter = cls()
    elif model == "mock" or model == "oracle-mock":
        adapter = get_adapter(mode="mock", model=model)
    else:
        # Attempt registry lookup (live / registered providers)
        adapter = get_adapter(provider=model, model=model, mode="live")

    if use_cache:
        try:
            from dl.vision.cache import CachedVisionAdapter
            cache_dir = output_dir / ".cache"
            adapter = CachedVisionAdapter(inner_adapter=adapter, cache_dir=cache_dir)
            logger.info("CachedVisionAdapter enabled (cache_dir=%s).", cache_dir)
        except Exception as exc:
            logger.warning("CachedVisionAdapter unavailable: %s. Proceeding without cache.", exc)

    return adapter


# ---------------------------------------------------------------------------
# Run-log persistence
# ---------------------------------------------------------------------------

def _save_run_log(output_dir: Path, log: RunLog) -> Path:
    """Write the run log as JSON and return its path."""
    path = output_dir / f"{log.run_id}.log.json"

    # Convert dataclasses to dicts (scenes is a list of dataclasses)
    data: dict[str, Any] = asdict(log)

    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Run log written: %s", path)
    return path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m dl.vision.runner",
        description="DisasterLens Vision AI batch runner.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        metavar="DIR",
        help="Dataset root directory (e.g. datasets/v1).",
    )
    p.add_argument(
        "--split",
        choices=["dev", "test"],
        default="dev",
        help="Dataset split to process.",
    )
    p.add_argument(
        "--model",
        default="mock",
        metavar="MODEL",
        help="Model or adapter name (e.g. mock, always-clear, proximity, noisy-oracle).",
    )
    p.add_argument(
        "--prompt-version",
        default="v1",
        metavar="VERSION",
        dest="prompt_version",
        help="Prompt version string.",
    )
    p.add_argument(
        "--image-variant",
        choices=["plain", "labelled"],
        default="plain",
        dest="image_variant",
        help="Which image variant to send to the model.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="DIR",
        help="Output directory for predictions and run log.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help=f"Thread pool size ({MIN_WORKERS}–{MAX_WORKERS}).",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Disable CachedVisionAdapter wrapping.",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code (0 = success, 1 = any failure)."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log = run_batch(
        dataset_dir=args.dataset,
        split=args.split,
        model=args.model,
        prompt_version=args.prompt_version,
        image_variant=args.image_variant,
        output_dir=args.output,
        workers=args.workers,
        use_cache=not args.no_cache,
    )

    # Summary report
    print(f"\n{'='*55}")
    print(f"Run: {log.run_id}")
    print(f"Dataset: {log.dataset_dir}")
    print(f"Model:   {log.model}  |  Prompt: {log.prompt_version}")
    print(f"Scenes:  total={log.total_scenes}  processed={log.processed}  "
          f"skipped={log.skipped}  failed={log.failed}")
    print(f"Output:  {log.output_dir}")
    print(f"{'='*55}\n")

    return 1 if log.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

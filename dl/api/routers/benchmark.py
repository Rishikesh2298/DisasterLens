import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])
RESULTS_DIR = Path(os.getenv("DISASTERLENS_RESULTS_DIR", "results"))


def _run_dir(run_id: str) -> Path:
    if not run_id or Path(run_id).name != run_id or run_id in (".", ".."):
        raise HTTPException(404, "Run not found")
    path = (RESULTS_DIR / run_id).resolve()
    if not path.is_relative_to(RESULTS_DIR.resolve()):
        raise HTTPException(404, "Run not found")
    if not path.is_dir():
        raise HTTPException(404, "Run not found")
    return path


def _read(run_id: str, filename: str):
    path = _run_dir(run_id) / filename
    if not path.is_file():
        raise HTTPException(404, f"{filename} not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "Saved result is invalid") from exc


@router.get("/runs")
def list_runs():
    if not RESULTS_DIR.exists():
        return {"runs": []}
    runs = []
    for directory in sorted((p for p in RESULTS_DIR.iterdir() if p.is_dir()), key=lambda p: p.name):
        summary = directory / "summary.json"
        if summary.is_file():
            try:
                item = json.loads(summary.read_text(encoding="utf-8"))
                runs.append(
                    {
                        "id": directory.name,
                        "run_name": item.get("run_name", directory.name),
                        "model_id": item.get("model_id", "unknown"),
                        "split": item.get("split", "dev"),
                        "is_mock": bool(item.get("is_mock", False)),
                        "scene_count": item.get("scene_count", 0),
                    }
                )
            except (OSError, json.JSONDecodeError):
                continue
    return {"runs": runs}


@router.get("/runs/{run_id}")
def run_summary(run_id: str):
    return {**_read(run_id, "summary.json"), "id": run_id}


@router.get("/runs/{run_id}/failures")
def run_failures(run_id: str, category: str | None = None, difficulty: str | None = None):
    failures = _read(run_id, "failures.json")
    return {
        "failures": [
            item
            for item in failures
            if (not category or item.get("category") == category)
            and (not difficulty or item.get("difficulty") == difficulty)
        ]
    }


@router.get("/runs/{run_id}/scenes/{scene_id}")
def scene_detail(run_id: str, scene_id: str):
    scenes = _read(run_id, "per_scene.json")
    for scene in scenes:
        if scene.get("scene_id") == scene_id:
            return scene
    raise HTTPException(404, "Scene not found")

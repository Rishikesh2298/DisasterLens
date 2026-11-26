import json

import pytest
from fastapi import HTTPException

from dl.api import main as api
from dl.api.routers import benchmark


def test_benchmark_api_reads_summary_and_filters_failures(tmp_path, monkeypatch):
    assert "http://127.0.0.1:5173" in api.origins
    run = tmp_path / "demo"
    run.mkdir()
    (run / "summary.json").write_text(
        json.dumps(
            {
                "run_name": "demo",
                "model_id": "mock",
                "split": "dev",
                "is_mock": True,
                "scene_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (run / "failures.json").write_text(
        json.dumps(
            [
                {"scene_id": "S-1", "category": "false_clear", "difficulty": "hard"},
                {"scene_id": "S-2", "category": "wrong_zone", "difficulty": "easy"},
            ]
        ),
        encoding="utf-8",
    )
    (run / "per_scene.json").write_text(
        json.dumps(
            [
                {
                    "scene_id": "S-1",
                    "truth": {"segments": {"SEG-1": "blocked"}},
                    "prediction": {"segments": {"SEG-1": "clear"}},
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(benchmark, "RESULTS_DIR", tmp_path)
    assert api.health()["status"] == "ok"
    assert benchmark.list_runs()["runs"][0]["run_name"] == "demo"
    assert benchmark.list_runs()["runs"][0]["id"] == "demo"
    assert len(benchmark.run_failures("demo", category="false_clear")["failures"]) == 1
    assert benchmark.scene_detail("demo", "S-1")["truth"]["segments"]["SEG-1"] == "blocked"
    with pytest.raises(HTTPException) as exc:
        benchmark.run_summary("../README.md")
    assert exc.value.status_code == 404

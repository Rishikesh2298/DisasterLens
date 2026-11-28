"""Run all benchmark scorers over scene and prediction JSON files."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path

from pydantic import ValidationError

from dl.contracts.evaluation import EvaluationDataset, EvaluationSummary, MetricResult
from dl.evaluation.calibration import score_calibration
from dl.evaluation.failures import classify_failures
from dl.evaluation.route_impact import score_route_impact
from dl.evaluation.tasks.counts import score_counts
from dl.evaluation.tasks.detection import score_detection
from dl.evaluation.tasks.reliability import score_reliability
from dl.evaluation.tasks.route import score_routes
from dl.evaluation.tasks.segment import score_segments
from dl.evaluation.tasks.water import score_water
from dl.evaluation.tasks.zone import score_zones


def evaluate(
    scenes, run_name="local", split="dev", model_id="unknown", prompt_version=None, is_mock=False
):
    detection = score_detection(scenes)
    detection_primary = dict(detection["iou_0.5"])
    detection_primary["iou_0.3"] = detection["iou_0.3"]
    tasks = {
        "detection": detection_primary,
        "segments": score_segments(scenes),
        "counts": score_counts(scenes),
        "water": score_water(scenes),
        "routes": score_routes(scenes),
        "zones": score_zones(scenes),
        "calibration": score_calibration(scenes),
        "reliability": score_reliability(scenes),
    }
    primary = {name: result for name, result in tasks.items()}
    for name, result in list(primary.items()):
        primary[name] = MetricResult(
            task=name,
            metrics={k: v for k, v in result.items() if isinstance(v, (int, float)) or v is None},
            details={
                k: v for k, v in result.items() if not isinstance(v, (int, float)) and v is not None
            },
        )
    summary = EvaluationSummary(
        run_name=run_name,
        model_id=model_id,
        prompt_version=prompt_version,
        split=split,
        is_mock=is_mock,
        created_at=datetime.now(UTC),
        scene_count=len(scenes),
        metrics=primary,
        route_impact=score_route_impact(scenes),
        failures=classify_failures(scenes),
    )
    return summary


def load_scenes(dataset_path: Path, predictions_path: Path):
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
    ds_scenes = dataset.get("scenes", dataset) if isinstance(dataset, dict) else dataset
    pred_scenes = (
        predictions.get("scenes", predictions) if isinstance(predictions, dict) else predictions
    )
    if isinstance(ds_scenes, list) and isinstance(pred_scenes, list):
        dataset_ids = _validate_scene_records(ds_scenes, "dataset")
        _validate_scene_records(pred_scenes, "predictions")
        try:
            validated_dataset = EvaluationDataset.model_validate({"scenes": ds_scenes})
        except ValidationError as exc:
            raise ValueError("Dataset scenes do not match the evaluation contract.") from exc
        normalized_scenes = [scene.model_dump(mode="json") for scene in validated_dataset.scenes]
        prediction_by_id = {scene["scene_id"]: scene for scene in pred_scenes}
        unknown_ids = set(prediction_by_id) - set(dataset_ids)
        if unknown_ids:
            raise ValueError(f"Predictions contain unknown scene IDs: {sorted(unknown_ids)}")
        return [
            _join_prediction(scene, prediction_by_id.get(scene["scene_id"]))
            for scene in normalized_scenes
        ]
    raise ValueError("Both JSON files must contain a 'scenes' list (or be lists themselves).")


def _validate_scene_records(records, label: str):
    identifiers = []
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("scene_id"), str)
            or not record["scene_id"]
        ):
            raise TypeError(f"Every {label} record must be an object with a string scene_id.")
        identifiers.append(record["scene_id"])
    duplicates = sorted(scene_id for scene_id, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate scene IDs in {label}: {duplicates}")
    return identifiers


def _join_prediction(scene, prediction_record):
    joined = dict(scene)
    if prediction_record is None:
        joined["prediction"] = {"valid_json": False, "raw_output": None}
        return joined
    prediction = prediction_record.get("prediction", prediction_record.get("analysis"))
    if prediction is None and any(
        key in prediction_record
        for key in ("hazards", "segments", "segment_verdicts", "water_regions")
    ):
        prediction = {key: value for key, value in prediction_record.items() if key != "scene_id"}
    if not isinstance(prediction, dict):
        joined["prediction"] = {
            "valid_json": False,
            "raw_output": prediction,
        }
        return joined
    prediction = _normalize_vision_prediction(prediction)
    if prediction.get("valid_json") is False:
        joined["prediction"] = prediction
        return joined
    errors = _prediction_shape_errors(prediction)
    if errors:
        joined["prediction"] = {
            "valid_json": False,
            "raw_output": prediction,
            "validation_errors": errors,
        }
        return joined
    joined["prediction"] = prediction
    return joined


def _normalize_vision_prediction(prediction: dict):
    """Adapt the shared SceneAnalysis contract into the scorer's flat status maps."""
    if "segments" in prediction or not isinstance(prediction.get("segment_verdicts"), dict):
        return prediction
    normalized = dict(prediction)
    segments = {}
    raw_details = normalized.get("segment_details", {})
    if not isinstance(raw_details, dict):
        return normalized
    details = dict(raw_details)
    for segment_id, verdict in normalized["segment_verdicts"].items():
        if not isinstance(verdict, dict):
            segments[segment_id] = verdict
            continue
        status = verdict.get("status")
        segments[segment_id] = status
        confidence = verdict.get("confidence")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and status in ("blocked", "clear")
        ):
            existing = details.get(segment_id, {})
            if not isinstance(existing, dict):
                continue
            details[segment_id] = {
                **existing,
                "blocked_confidence": confidence if status == "blocked" else 1 - confidence,
            }
    normalized["segments"] = segments
    normalized["segment_details"] = details
    return normalized


def _prediction_shape_errors(prediction: dict):
    errors = []
    if "valid_json" in prediction and not isinstance(prediction["valid_json"], bool):
        errors.append("valid_json must be a boolean")
    hazards = prediction.get("hazards", [])
    if not isinstance(hazards, list):
        errors.append("hazards must be a list")
    else:
        for index, hazard in enumerate(hazards):
            if not isinstance(hazard, dict) or not isinstance(hazard.get("type"), str):
                errors.append(f"hazards[{index}] must include a string type")
                continue
            if not _valid_box(hazard.get("bbox")):
                errors.append(f"hazards[{index}].bbox must be an ordered pixel box")
            confidence = hazard.get("confidence")
            if confidence is not None and (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                errors.append(f"hazards[{index}].confidence must be between 0 and 1")
    segments = prediction.get("segments", {})
    if not isinstance(segments, dict):
        errors.append("segments must be a mapping")
    elif any(
        not isinstance(status, str)
        or status not in {"blocked", "partial", "clear", "uncertain", "stale", "unknown"}
        for status in segments.values()
    ):
        errors.append("segments contain an unsupported road status")
    verdicts = prediction.get("segment_verdicts", {})
    if not isinstance(verdicts, dict):
        errors.append("segment_verdicts must be a mapping")
    else:
        for segment_id, verdict in verdicts.items():
            if not isinstance(verdict, dict):
                errors.append(f"segment_verdicts[{segment_id!r}] must be a mapping")
                continue
            status = verdict.get("status")
            confidence = verdict.get("confidence")
            if not isinstance(status, str) or status not in {
                "blocked",
                "partial",
                "clear",
                "uncertain",
                "stale",
                "unknown",
            }:
                errors.append(f"segment_verdicts[{segment_id!r}].status is unsupported")
            if confidence is not None and (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not isfinite(confidence)
                or not 0 <= confidence <= 0.85
            ):
                errors.append(f"segment_verdicts[{segment_id!r}].confidence must be at most 0.85")
    count = prediction.get("damaged_building_count")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
        errors.append("damaged_building_count must be a non-negative integer")
    water_regions = prediction.get("water_regions", [])
    if not isinstance(water_regions, list) or any(
        not isinstance(region, dict) or not _valid_box(region.get("bbox"))
        for region in water_regions
    ):
        errors.append("water_regions must be a list of records with ordered pixel boxes")
    for key in ("routes", "zone_comparisons", "segment_details"):
        value = prediction.get(key, {})
        if not isinstance(value, dict):
            errors.append(f"{key} must be a mapping")
    segment_details = prediction.get("segment_details", {})
    if isinstance(segment_details, dict):
        for segment_id, detail in segment_details.items():
            if not isinstance(detail, dict):
                errors.append(f"segment_details[{segment_id!r}] must be a mapping")
                continue
            confidence = detail.get("blocked_confidence")
            if confidence is not None and (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                errors.append(
                    f"segment_details[{segment_id!r}].blocked_confidence must be between 0 and 1"
                )
    elif "segment_details" in prediction:
        errors.append("segment_details must be a mapping")
    latency = prediction.get("latency_ms")
    if latency is not None and (
        not isinstance(latency, (int, float))
        or isinstance(latency, bool)
        or not isfinite(latency)
        or latency < 0
    ):
        errors.append("latency_ms must be non-negative")
    return errors


def _valid_box(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(
            isinstance(coordinate, (int, float)) and not isinstance(coordinate, bool)
            for coordinate in value
        )
        and all(isfinite(coordinate) for coordinate in value)
        and value[2] >= value[0]
        and value[3] >= value[1]
    )


def load_prediction_metadata(predictions_path: Path):
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
    if not isinstance(predictions, dict):
        return {}
    metadata = dict(predictions)
    records = predictions.get("scenes", [])
    if not isinstance(records, list):
        raise TypeError("Prediction document 'scenes' must be a list.")
    record_values = {"model_id": set(), "prompt_version": set(), "is_mock": set()}
    for record in records:
        if not isinstance(record, dict):
            continue
        response = record.get("prediction", record.get("analysis", record))
        if not isinstance(response, dict):
            continue
        for key, values in record_values.items():
            value = response.get(key, record.get(key))
            if value is not None:
                expected_type = bool if key == "is_mock" else str
                if not isinstance(value, expected_type):
                    raise ValueError(f"Prediction scene {key} must be {expected_type.__name__}.")
                values.add(value)
    for key, values in record_values.items():
        if len(values) > 1:
            raise ValueError(f"Prediction records mix multiple {key} values.")
        if key in metadata and values and metadata[key] not in values:
            raise ValueError(f"Prediction document metadata conflicts with scene-level {key}.")
        if key not in metadata and values:
            metadata[key] = next(iter(values))
    if "is_mock" in metadata and not isinstance(metadata["is_mock"], bool):
        raise ValueError("Prediction document is_mock metadata must be boolean.")
    return metadata


def select_split(scenes, split: str):
    labels = {scene.get("split") for scene in scenes}
    if not labels or None in labels:
        raise ValueError("Every dataset scene must declare its split (dev or test).")
    invalid = labels - {"dev", "test"}
    if invalid:
        raise ValueError(f"Unknown dataset split(s): {sorted(invalid)}")
    selected = [scene for scene in scenes if scene["split"] == split]
    if not selected:
        raise ValueError(f"The dataset has no scenes in the requested {split!r} split.")
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", default=Path("results/local"), type=Path)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--run-name", default="local")
    parser.add_argument("--model-id")
    parser.add_argument("--prompt-version")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    scenes = select_split(load_scenes(args.dataset, args.predictions), args.split)
    prediction_metadata = load_prediction_metadata(args.predictions)
    summary = evaluate(
        scenes,
        args.run_name,
        args.split,
        args.model_id or prediction_metadata.get("model_id", "unknown"),
        args.prompt_version or prediction_metadata.get("prompt_version"),
        args.mock or bool(prediction_metadata.get("is_mock", False)),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "summary.json"
    summary_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    (args.output / "failures.json").write_text(
        json.dumps([f.model_dump() for f in summary.failures], indent=2), encoding="utf-8"
    )
    per_scene = [
        {
            "scene_id": s.get("scene_id"),
            "difficulty": s.get("difficulty"),
            "truth": s.get("truth", {}),
            "prediction": s.get("prediction", {}),
        }
        for s in scenes
    ]
    (args.output / "per_scene.json").write_text(json.dumps(per_scene, indent=2), encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

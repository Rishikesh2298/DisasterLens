"""
evaluate_predictions.py
=======================
Offline ground-truth evaluation for DisasterLens segment-verdict predictions.

Compares predicted segment statuses against ground-truth segment statuses for
all 20 development scenes (S-0001 to S-0020) in a given predictions directory.

Usage
-----
    python scripts/evaluate_predictions.py \
        --predictions-dir results/predictions/dev/gemini-v2-plain-batch \
        --ground-truth-dir datasets/v1 \
        --output results/eval_plain_v2.json

Output
------
JSON report containing:
  - per_scene      : per-scene accuracy and per-status counts
  - overall        : aggregate confusion matrix, per-class P/R/F1, macro-F1
  - metadata       : paths, scene count, total segments, notes

Notes
-----
  - Segment statuses from ground truth are UPPERCASE (CLEAR/BLOCKED/PARTIAL).
    Prediction statuses are lowercase. Both are normalised to uppercase before
    comparison.
  - UNCERTAIN is not a ground-truth status; predictions of UNCERTAIN are
    scored as misclassifications.
  - Missing segment IDs in a prediction are treated as UNCERTAIN (error case).
  - Hazard bounding-box metrics cannot be computed: ground_truth.json does not
    contain hazard coordinates.
  - This script is read-only with respect to prediction and ground-truth files.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCENES = [f"S-{i:04d}" for i in range(1, 21)]
ALL_STATUSES = ["CLEAR", "BLOCKED", "PARTIAL", "UNCERTAIN"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _normalise_status(raw: str | None) -> str:
    """Uppercase-normalise a status string; return UNCERTAIN for None/empty."""
    if raw is None:
        return "UNCERTAIN"
    s = str(raw).strip().upper()
    if s not in ALL_STATUSES:
        return "UNCERTAIN"
    return s


def _safe_div(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _precision_recall_f1(
    tp: int, fp: int, fn: int
) -> tuple[float | None, float | None, float | None]:
    p = _safe_div(tp, tp + fp)
    r = _safe_div(tp, tp + fn)
    if p is not None and r is not None and (p + r) > 0:
        f1 = round(2 * p * r / (p + r), 4)
    else:
        f1 = None
    return p, r, f1


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_ground_truth(gt_dir: Path, scene_id: str) -> dict[str, str]:
    """Return {segment_id: UPPERCASE_STATUS} from ground_truth.json."""
    path = gt_dir / scene_id / "ground_truth.json"
    if not path.exists():
        raise FileNotFoundError(f"Ground truth not found: {path}")
    raw = _load_json(path)
    return {
        entry["segment_id"]: _normalise_status(entry["status"])
        for entry in raw["segment_statuses"]
    }


def load_predictions(pred_dir: Path, scene_id: str) -> dict[str, str]:
    """Return {segment_id: UPPERCASE_STATUS} from prediction JSON."""
    path = pred_dir / f"{scene_id}_prediction.json"
    if not path.exists():
        raise FileNotFoundError(f"Prediction not found: {path}")
    raw = _load_json(path)
    verdicts = raw.get("segment_verdicts", {})
    return {
        seg_id: _normalise_status(v.get("status") if isinstance(v, dict) else None)
        for seg_id, v in verdicts.items()
    }


# ---------------------------------------------------------------------------
# Per-scene evaluation
# ---------------------------------------------------------------------------

def evaluate_scene(
    scene_id: str,
    gt: dict[str, str],
    pred: dict[str, str],
) -> dict[str, Any]:
    """Evaluate a single scene; return per-scene result dict."""
    correct = 0
    total = len(gt)
    status_counts: dict[str, dict[str, int]] = {
        s: {"tp": 0, "fp": 0, "fn": 0} for s in ALL_STATUSES
    }
    # confusion matrix: conf[actual][predicted] = count
    conf: dict[str, dict[str, int]] = {
        a: {p: 0 for p in ALL_STATUSES} for a in ALL_STATUSES
    }

    missing_segs: list[str] = []
    for seg_id, actual in gt.items():
        predicted = pred.get(seg_id)
        if predicted is None:
            # segment absent from prediction → treat as UNCERTAIN
            missing_segs.append(seg_id)
            predicted = "UNCERTAIN"

        conf[actual][predicted] += 1

        if actual == predicted:
            correct += 1
            status_counts[actual]["tp"] += 1
        else:
            status_counts[actual]["fn"] += 1
            status_counts[predicted]["fp"] += 1

    accuracy = _safe_div(correct, total)
    extra_segs = [s for s in pred if s not in gt]

    return {
        "scene_id": scene_id,
        "total_segments": total,
        "correct": correct,
        "accuracy": accuracy,
        "missing_segments": missing_segs,
        "extra_segments_in_pred": extra_segs,
        "per_status_counts": {
            s: {"gt_count": sum(1 for v in gt.values() if v == s),
                "pred_count": sum(1 for v in pred.values() if v == s),
                **status_counts[s]}
            for s in ALL_STATUSES
        },
        "confusion_row": {actual: conf[actual] for actual in ALL_STATUSES},
    }


# ---------------------------------------------------------------------------
# Aggregate evaluation
# ---------------------------------------------------------------------------

def aggregate_results(scene_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-scene results into overall metrics."""
    total_correct = sum(r["correct"] for r in scene_results)
    total_segments = sum(r["total_segments"] for r in scene_results)
    total_missing = sum(len(r["missing_segments"]) for r in scene_results)

    # Accumulate confusion matrix
    conf: dict[str, dict[str, int]] = {
        a: {p: 0 for p in ALL_STATUSES} for a in ALL_STATUSES
    }
    for r in scene_results:
        for actual, preds in r["confusion_row"].items():
            for predicted, cnt in preds.items():
                conf[actual][predicted] += cnt

    # Per-class TP/FP/FN → P/R/F1
    per_class: dict[str, Any] = {}
    f1_values: list[float] = []
    for cls in ALL_STATUSES:
        tp = conf[cls][cls]
        fp = sum(conf[other][cls] for other in ALL_STATUSES if other != cls)
        fn = sum(conf[cls][other] for other in ALL_STATUSES if other != cls)
        p, r, f1 = _precision_recall_f1(tp, fp, fn)
        per_class[cls] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": p, "recall": r, "f1": f1,
            "gt_count": tp + fn,
        }
        if f1 is not None:
            f1_values.append(f1)

    macro_f1 = round(sum(f1_values) / len(f1_values), 4) if f1_values else None

    overall_accuracy = _safe_div(total_correct, total_segments)

    # UNCERTAIN rate
    uncertain_predicted = sum(conf[a]["UNCERTAIN"] for a in ALL_STATUSES)
    uncertain_rate = _safe_div(uncertain_predicted, total_segments)

    return {
        "scene_count": len(scene_results),
        "total_segments": total_segments,
        "total_correct": total_correct,
        "total_missing_in_pred": total_missing,
        "overall_accuracy": overall_accuracy,
        "macro_f1": macro_f1,
        "blocked_recall": per_class["BLOCKED"]["recall"],
        "uncertain_predicted_count": uncertain_predicted,
        "uncertain_rate": uncertain_rate,
        "per_class": per_class,
        "confusion_matrix": conf,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate DisasterLens predictions against ground truth."
    )
    p.add_argument(
        "--predictions-dir",
        required=True,
        type=Path,
        help="Directory containing S-XXXX_prediction.json files.",
    )
    p.add_argument(
        "--ground-truth-dir",
        default=Path("datasets/v1"),
        type=Path,
        help="Root directory containing S-XXXX/ground_truth.json files. "
             "Default: datasets/v1",
    )
    p.add_argument(
        "--output",
        default=None,
        type=Path,
        help="Write JSON report to this file. Defaults to stdout.",
    )
    p.add_argument(
        "--scenes",
        nargs="*",
        default=SCENES,
        help="Scene IDs to evaluate (default: all 20 dev scenes).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    pred_dir = args.predictions_dir.resolve()
    gt_dir = args.ground_truth_dir.resolve()

    if not pred_dir.exists():
        print(f"ERROR: Predictions directory not found: {pred_dir}", file=sys.stderr)
        return 1
    if not gt_dir.exists():
        print(f"ERROR: Ground-truth directory not found: {gt_dir}", file=sys.stderr)
        return 1

    scene_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for scene_id in args.scenes:
        try:
            gt = load_ground_truth(gt_dir, scene_id)
            pred = load_predictions(pred_dir, scene_id)
            result = evaluate_scene(scene_id, gt, pred)
            scene_results.append(result)
        except FileNotFoundError as exc:
            errors.append(str(exc))
            print(f"WARNING: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{scene_id}: {exc}")
            print(f"ERROR ({scene_id}): {exc}", file=sys.stderr)

    if not scene_results:
        print("ERROR: No scenes could be evaluated.", file=sys.stderr)
        return 1

    overall = aggregate_results(scene_results)

    report: dict[str, Any] = {
        "metadata": {
            "predictions_dir": str(pred_dir),
            "ground_truth_dir": str(gt_dir),
            "scenes_requested": len(args.scenes),
            "scenes_evaluated": len(scene_results),
            "errors": errors,
            "notes": [
                "Hazard bounding-box metrics not computed: ground_truth.json "
                "does not contain hazard coordinates.",
                "UNCERTAIN is not a ground-truth class; predicted UNCERTAIN "
                "counts as a misclassification.",
                "Missing segment IDs in prediction are treated as UNCERTAIN.",
            ],
        },
        "overall": overall,
        "per_scene": scene_results,
    }

    json_str = json.dumps(report, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_str, encoding="utf-8")
        print(f"Report written to: {args.output}", file=sys.stderr)
    else:
        print(json_str)

    # Print summary to stderr always
    o = overall
    print(
        f"\n=== EVALUATION SUMMARY ===",
        f"Predictions : {pred_dir.name}",
        f"Scenes      : {o['scene_count']} / {len(args.scenes)}",
        f"Segments    : {o['total_segments']} total, {o['total_correct']} correct",
        f"Accuracy    : {o['overall_accuracy']:.4f}" if o["overall_accuracy"] is not None else "Accuracy    : N/A",
        f"Macro-F1    : {o['macro_f1']:.4f}" if o["macro_f1"] is not None else "Macro-F1    : N/A",
        f"BLOCKED Recall: {o['blocked_recall']:.4f}" if o["blocked_recall"] is not None else "BLOCKED Recall: N/A",
        f"UNCERTAIN rate: {o['uncertain_rate']:.4f}" if o["uncertain_rate"] is not None else "UNCERTAIN rate: N/A",
        sep="\n",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

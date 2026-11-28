from collections.abc import Mapping, Sequence
from typing import Any


def box_iou(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != 4 or len(right) != 4:
        raise ValueError("boxes must be [x1, y1, x2, y2]")
    ax1, ay1, ax2, ay2 = map(float, left)
    bx1, by1, bx2, by2 = map(float, right)
    if ax2 < ax1 or ay2 < ay1 or bx2 < bx1 or by2 < by1:
        raise ValueError("box coordinates must be ordered")
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def greedy_match(
    truth: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    threshold: float = 0.5,
):
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    ordered = sorted(
        enumerate(predictions), key=lambda pair: float(pair[1].get("confidence", 1.0)), reverse=True
    )
    matched_truth: set[int] = set()
    matches = []
    false_positives = []
    for pred_index, prediction in ordered:
        candidates = [
            (box_iou(prediction["bbox"], actual["bbox"]), truth_index)
            for truth_index, actual in enumerate(truth)
            if truth_index not in matched_truth and actual.get("type") == prediction.get("type")
        ]
        overlap, truth_index = max(candidates, default=(0.0, -1))
        if overlap > 0 and overlap >= threshold:
            matched_truth.add(truth_index)
            matches.append(
                {"truth_index": truth_index, "prediction_index": pred_index, "iou": overlap}
            )
        else:
            false_positives.append(pred_index)
    return {
        "matches": matches,
        "false_positives": false_positives,
        "false_negatives": [i for i in range(len(truth)) if i not in matched_truth],
    }

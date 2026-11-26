from collections.abc import Iterable, Sequence


def precision(tp: int, fp: int) -> float:
    return tp / (tp + fp) if tp + fp else 0.0


def recall(tp: int, fn: int) -> float:
    return tp / (tp + fn) if tp + fn else 0.0


def f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


def prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    p, r = precision(tp, fp), recall(tp, fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1(p, r)}


def confusion_matrix(truth: Sequence[str], prediction: Sequence[str], labels: Sequence[str]):
    if len(truth) != len(prediction):
        raise ValueError("truth and prediction must have the same length")
    matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    for actual, predicted in zip(truth, prediction, strict=True):
        if actual not in matrix or predicted not in matrix[actual]:
            raise ValueError(f"unknown label: {actual!r} or {predicted!r}")
        matrix[actual][predicted] += 1
    return matrix


def classification_scores(truth: Sequence[str], prediction: Sequence[str], labels: Sequence[str]):
    matrix = confusion_matrix(truth, prediction, labels)
    per_class = {}
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[actual][label] for actual in labels if actual != label)
        fn = sum(matrix[label][predicted] for predicted in labels if predicted != label)
        per_class[label] = prf(tp, fp, fn)
    total = len(truth)
    return {
        "accuracy": sum(matrix[k][k] for k in labels) / total if total else 0.0,
        # Do not penalize a run for a class that appears in neither truth nor predictions.
        "macro_f1": (
            sum(
                per_class[label]["f1"]
                for label in labels
                if sum(matrix[label].values()) + sum(matrix[row][label] for row in labels) > 0
            )
            / sum(
                1
                for label in labels
                if sum(matrix[label].values()) + sum(matrix[row][label] for row in labels) > 0
            )
            if any(
                sum(matrix[label].values()) + sum(matrix[row][label] for row in labels) > 0
                for label in labels
            )
            else 0.0
        ),
        "per_class": per_class,
        "confusion_matrix": matrix,
    }


def mean_absolute_error(truth: Iterable[float], prediction: Iterable[float]) -> float:
    pairs = list(zip(truth, prediction, strict=True))
    return sum(abs(a - b) for a, b in pairs) / len(pairs) if pairs else 0.0


def brier_score(truth: Sequence[int], confidence: Sequence[float]) -> float:
    if len(truth) != len(confidence):
        raise ValueError("truth and confidence must have the same length")
    if any(not 0 <= score <= 1 for score in confidence):
        raise ValueError("confidence values must be between 0 and 1")
    return (
        sum((p - y) ** 2 for y, p in zip(truth, confidence, strict=True)) / len(truth)
        if truth
        else 0.0
    )


def calibration_bins(truth: Sequence[int], confidence: Sequence[float], bins: int = 5):
    if bins < 1 or len(truth) != len(confidence):
        raise ValueError("bins must be positive and truth/confidence lengths must match")
    if any(not 0 <= score <= 1 for score in confidence):
        raise ValueError("confidence values must be between 0 and 1")
    result = []
    for index in range(bins):
        items = [
            (y, p)
            for y, p in zip(truth, confidence, strict=True)
            if min(int(p * bins), bins - 1) == index
        ]
        result.append(
            {
                "lower": index / bins,
                "upper": (index + 1) / bins,
                "count": len(items),
                "mean_confidence": sum(p for _, p in items) / len(items) if items else 0.0,
                "hit_rate": sum(y for y, _ in items) / len(items) if items else 0.0,
            }
        )
    return result

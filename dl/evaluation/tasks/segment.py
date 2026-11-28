from dl.evaluation.metrics import classification_scores

LABELS = ("blocked", "partial", "clear", "uncertain")


def score_segments(scenes):
    truth, predicted = [], []
    for scene in scenes:
        actual = scene.get("truth", {}).get("segments", {})
        guess = scene.get("prediction", {}).get("segments", {})
        for segment_id, status in actual.items():
            truth.append(status)
            value = guess.get(segment_id, "uncertain")
            predicted.append(value if value in LABELS else "uncertain")
    result = classification_scores(truth, predicted, LABELS)
    matrix = result["confusion_matrix"]
    blocked_total = sum(matrix["blocked"].values())
    result["false_clear_rate"] = matrix["blocked"]["clear"] / len(truth) if truth else 0.0
    result["blocked_miss_rate"] = (
        matrix["blocked"]["clear"] / blocked_total if blocked_total else 0.0
    )
    result["false_block_rate"] = (
        matrix["clear"]["blocked"] / sum(matrix["clear"].values())
        if sum(matrix["clear"].values())
        else 0.0
    )
    result["uncertain_rate"] = predicted.count("uncertain") / len(predicted) if predicted else 0.0
    return result

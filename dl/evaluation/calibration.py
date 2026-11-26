from dl.evaluation.metrics import brier_score, calibration_bins


def score_calibration(scenes, bins=5):
    truth, confidence = [], []
    for scene in scenes:
        actual = scene.get("truth", {}).get("segments", {})
        predicted = scene.get("prediction", {}).get("segment_details", {})
        for segment_id, status in actual.items():
            if segment_id in predicted and "blocked_confidence" in predicted[segment_id]:
                truth.append(int(status == "blocked"))
                confidence.append(float(predicted[segment_id]["blocked_confidence"]))
    return {
        "brier_score": brier_score(truth, confidence),
        "bins": calibration_bins(truth, confidence, bins),
        "count": len(truth),
    }

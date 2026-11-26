from dl.evaluation.matching import box_iou, greedy_match
from dl.evaluation.metrics import prf


def score_water(scenes, threshold=0.5):
    tp = fp = fn = 0
    overlaps = []
    for scene in scenes:
        truth = scene.get("truth", {}).get("water_regions", [])
        pred = scene.get("prediction", {}).get("water_regions", [])
        # Water regions use the same {type, bbox} contract as hazards.
        paired = greedy_match(
            [dict(x, type="water") for x in truth], [dict(x, type="water") for x in pred], threshold
        )
        tp += len(paired["matches"])
        fp += len(paired["false_positives"])
        fn += len(paired["false_negatives"])
        overlaps.extend(
            box_iou(pred[m["prediction_index"]]["bbox"], truth[m["truth_index"]]["bbox"])
            for m in paired["matches"]
        )
    return {**prf(tp, fp, fn), "mean_iou": sum(overlaps) / len(overlaps) if overlaps else 0.0}

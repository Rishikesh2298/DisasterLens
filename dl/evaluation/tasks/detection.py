from collections import Counter, defaultdict

from dl.evaluation.matching import greedy_match
from dl.evaluation.metrics import prf


def score_detection(scenes, thresholds=(0.5, 0.3)):
    output = {}
    for threshold in thresholds:
        totals = Counter()
        per_type = defaultdict(Counter)
        for scene in scenes:
            truth = scene.get("truth", {}).get("hazards", [])
            pred = scene.get("prediction", {}).get("hazards", [])
            result = greedy_match(truth, pred, threshold)
            totals.update(
                {
                    "tp": len(result["matches"]),
                    "fp": len(result["false_positives"]),
                    "fn": len(result["false_negatives"]),
                }
            )
            types = {x.get("type", "unknown") for x in truth} | {
                x.get("type", "unknown") for x in pred
            }
            for hazard_type in types:
                actual = [x for x in truth if x.get("type", "unknown") == hazard_type]
                guessed = [x for x in pred if x.get("type", "unknown") == hazard_type]
                matched = greedy_match(actual, guessed, threshold)
                per_type[hazard_type].update(
                    {
                        "tp": len(matched["matches"]),
                        "fp": len(matched["false_positives"]),
                        "fn": len(matched["false_negatives"]),
                    }
                )
        scores = {
            key: prf(value["tp"], value["fp"], value["fn"])
            for key, value in sorted(per_type.items())
        }
        output[f"iou_{threshold:.1f}"] = {
            **prf(totals["tp"], totals["fp"], totals["fn"]),
            "macro_f1": sum(x["f1"] for x in scores.values()) / len(scores) if scores else 0.0,
            "per_class": scores,
        }
    return output

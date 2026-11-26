from dl.evaluation.metrics import mean_absolute_error


def score_counts(scenes):
    pairs = [
        (
            scene.get("truth", {}).get("damaged_building_count", 0),
            scene.get("prediction", {}).get("damaged_building_count", 0),
        )
        for scene in scenes
    ]
    return {
        "exact_match": sum(a == b for a, b in pairs) / len(pairs) if pairs else 0.0,
        "mae": mean_absolute_error((a for a, _ in pairs), (b for _, b in pairs)),
        "count": len(pairs),
    }

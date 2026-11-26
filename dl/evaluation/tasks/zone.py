def score_zones(scenes):
    total = correct = 0
    for scene in scenes:
        actual = scene.get("truth", {}).get("zone_comparisons", {})
        predicted = scene.get("prediction", {}).get("zone_comparisons", {})
        for question, answer in actual.items():
            if answer == "tie":
                continue
            total += 1
            correct += predicted.get(question) == answer
    return {"accuracy": correct / total if total else 0.0, "count": total}

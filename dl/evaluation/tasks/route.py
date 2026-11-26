from dl.evaluation.metrics import prf


def score_routes(scenes):
    total = correct = near_total = near_correct = tp = fp = fn = 0
    for scene in scenes:
        truth = scene.get("truth", {}).get("routes", {})
        pred = scene.get("prediction", {}).get("routes", {})
        near = set(scene.get("near_miss_questions", []))
        for question, answer in truth.items():
            guess = pred.get(question, "uncertain")
            total += 1
            correct += guess == answer
            if answer == "obstructed":
                if guess == "obstructed":
                    tp += 1
                else:
                    fn += 1
            elif guess == "obstructed":
                fp += 1
            if question in near:
                near_total += 1
                near_correct += guess == answer
    return {
        "accuracy": correct / total if total else 0.0,
        "obstructed": prf(tp, fp, fn),
        "near_miss_accuracy": near_correct / near_total if near_total else 0.0,
        "count": total,
        "near_miss_count": near_total,
    }

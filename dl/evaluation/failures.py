from dl.evaluation.matching import greedy_match


def classify_failures(scenes):
    failures = []
    for scene in scenes:
        scene_id = scene.get("scene_id", "unknown")
        truth, pred = scene.get("truth", {}), scene.get("prediction", {})
        base = {"scene_id": scene_id, "difficulty": scene.get("difficulty")}
        if pred.get("valid_json") is False:
            failures.append(
                {
                    **base,
                    "category": "invalid_output",
                    "question": "response_json",
                    "prediction": pred.get("raw_output"),
                    "truth": "valid structured response",
                }
            )
        for segment_id, status in truth.get("segments", {}).items():
            guess = pred.get("segments", {}).get(segment_id, "uncertain")
            if guess == status:
                continue
            category = (
                "false_clear"
                if status == "blocked" and guess == "clear"
                else "near_miss_false_block"
                if status == "clear"
                and guess == "blocked"
                and segment_id in scene.get("near_miss_segments", [])
                else "false_block"
                if status == "clear" and guess == "blocked"
                else "partial_confusion"
                if "partial" in (status, guess)
                else "missed_small_hazard"
                if status == "blocked" and guess in ("uncertain", "unknown", "stale")
                else None
            )
            if category:
                failures.append(
                    {
                        **base,
                        "category": category,
                        "question": segment_id,
                        "prediction": guess,
                        "truth": status,
                    }
                )
        if truth.get("damaged_building_count") != pred.get("damaged_building_count"):
            failures.append(
                {
                    **base,
                    "category": "count_error",
                    "question": "damaged_building_count",
                    "prediction": pred.get("damaged_building_count"),
                    "truth": truth.get("damaged_building_count"),
                }
            )
        for q, answer in truth.get("routes", {}).items():
            guess = pred.get("routes", {}).get(q)
            if guess != answer:
                if answer == "obstructed":
                    category = "missed_small_hazard"
                elif q in scene.get("near_miss_questions", []):
                    category = "near_miss_false_block"
                else:
                    category = "false_block"
                failures.append(
                    {
                        **base,
                        "category": category,
                        "question": q,
                        "prediction": guess,
                        "truth": answer,
                    }
                )
        for q, answer in truth.get("zone_comparisons", {}).items():
            if answer != "tie" and pred.get("zone_comparisons", {}).get(q) != answer:
                failures.append(
                    {
                        **base,
                        "category": "wrong_zone",
                        "question": q,
                        "prediction": pred.get("zone_comparisons", {}).get(q),
                        "truth": answer,
                    }
                )
        hazards = truth.get("hazards", [])
        pred_hazards = pred.get("hazards", [])
        matches = greedy_match(hazards, pred_hazards)
        for index in matches["false_positives"]:
            failures.append(
                {
                    **base,
                    "category": "invalid_output"
                    if pred_hazards[index].get("invalid")
                    else "false_hazard",
                    "question": "hazards",
                    "prediction": pred_hazards[index],
                    "truth": None,
                }
            )
        for index in matches["false_negatives"]:
            failures.append(
                {
                    **base,
                    "category": "missed_small_hazard",
                    "question": "hazards",
                    "prediction": None,
                    "truth": hazards[index],
                }
            )
    return failures

def score_reliability(scenes):
    valid = 0
    latencies = []
    for scene in scenes:
        prediction = scene.get("prediction", {})
        valid += bool(prediction.get("valid_json", True))
        if prediction.get("latency_ms") is not None:
            latencies.append(float(prediction["latency_ms"]))
    return {
        "valid_json_rate": valid / len(scenes) if scenes else 0.0,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "scene_count": len(scenes),
        "latency_count": len(latencies),
    }

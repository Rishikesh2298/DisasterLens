from collections.abc import Mapping
from heapq import heappop, heappush


def shortest_path(
    graph: Mapping, blocked: set[str] | None = None, penalized: set[str] | None = None
):
    """Return the minimum-distance path as segment IDs; disconnected graphs return []."""
    blocked, penalized = blocked or set(), penalized or set()
    start, destination = graph.get("origin"), graph.get("destination")
    edges = graph.get("segments", [])
    if start is None or destination is None:
        return []
    adjacency = {}
    for edge in edges:
        if edge["id"] in blocked:
            continue
        weight = float(edge.get("length", 1)) * (
            float(graph.get("unknown_penalty", 3)) if edge["id"] in penalized else 1
        )
        adjacency.setdefault(edge["from"], []).append((edge["to"], edge["id"], weight))
        adjacency.setdefault(edge["to"], []).append((edge["from"], edge["id"], weight))
    queue = [(0.0, start, [])]
    best = {}
    while queue:
        cost, node, path = heappop(queue)
        if node in best and cost >= best[node]:
            continue
        best[node] = cost
        if node == destination:
            return path
        for neighbor, edge_id, weight in adjacency.get(node, []):
            heappush(queue, (cost + weight, neighbor, [*path, edge_id]))
    return []


def score_route_impact(scenes, route_fn=shortest_path):
    total = unsafe = detours = 0
    extra = []
    by_difficulty = {}
    for scene in scenes:
        graph = scene.get("road_graph", {})
        truth = scene.get("truth", {}).get("segments", {})
        prediction = scene.get("prediction", {}).get("segments", {})
        for route in graph.get("routes", []):
            total += 1
            reference = route_fn(
                {**graph, **route}, blocked={k for k, v in truth.items() if v == "blocked"}
            )
            predicted = route_fn(
                {**graph, **route},
                blocked={k for k, v in prediction.items() if v == "blocked"},
                penalized={
                    k
                    for k, v in prediction.items()
                    if v in ("unknown", "uncertain", "stale", "partial")
                },
            )
            bad = bool(predicted and any(truth.get(segment) == "blocked" for segment in predicted))
            unsafe += bad
            ref_len = sum(
                float(e.get("length", 1)) for e in graph.get("segments", []) if e["id"] in reference
            )
            pred_len = sum(
                float(e.get("length", 1)) for e in graph.get("segments", []) if e["id"] in predicted
            )
            detour = bool(
                reference
                and pred_len > ref_len * 1.1
                and any(truth.get(s) == "clear" for s in reference if s not in predicted)
            )
            detours += detour
            extra.append(max(0.0, (pred_len - ref_len) / ref_len * 100) if ref_len else 0.0)
            level = scene.get("difficulty", "unknown")
            stats = by_difficulty.setdefault(level, {"routes": 0, "unsafe": 0, "detours": 0})
            stats["routes"] += 1
            stats["unsafe"] += bad
            stats["detours"] += detour
    for stats in by_difficulty.values():
        count = stats["routes"]
        stats["unsafe_rate"] = stats["unsafe"] / count if count else 0.0
        stats["unnecessary_detour_rate"] = stats["detours"] / count if count else 0.0
    return {
        "route_count": total,
        "unsafe_route_rate": unsafe / total if total else 0.0,
        "unnecessary_detour_rate": detours / total if total else 0.0,
        "mean_extra_distance_percent": sum(extra) / len(extra) if extra else 0.0,
        "by_difficulty": by_difficulty,
    }

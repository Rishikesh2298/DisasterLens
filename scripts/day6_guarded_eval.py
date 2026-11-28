"""Day 6: apply mapper + guards to the saved Labelled v2 predictions (offline, no API calls).
Development scenes only (synthetic data)."""
import json
from collections import Counter
from pathlib import Path

from dl.contracts.vision import SceneAnalysis
from dl.vision.guards import apply_guards
from dl.vision.mapper import map_hazards_to_roads
from dl.vision.runner import SceneLoader

PRED_DIR = Path("results/predictions/dev/gemini-v2-labelled-batch")
DATA_DIR = Path("datasets/v1")

raw_c, grd_c = Counter(), Counter()      # outcomes for real BLOCKED/PARTIAL segments
clear_total, clear_to_uncertain = 0, 0   # cost: real CLEAR segments turned UNCERTAIN
rules = Counter()
errors = 0

for scene_dir in sorted(DATA_DIR.glob("S-*")):
    sid = scene_dir.name
    pred_path = PRED_DIR / f"{sid}_prediction.json"
    try:
        analysis = SceneAnalysis.model_validate_json(pred_path.read_text(encoding="utf-8"))
        scene = SceneLoader(scene_dir, split="dev").load_scene()
        gt = json.loads((scene_dir / "ground_truth.json").read_text(encoding="utf-8"))
        gt_status = {s["segment_id"]: s["status"].lower() for s in gt["segment_statuses"]}
        segs = [s for s in scene.segments
                if s.polygon and len(s.polygon) >= 3 and s.centerline and len(s.centerline) >= 2]
        mapped = map_hazards_to_roads(segments=segs, hazards=analysis.hazards) if segs else {}
        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
    except Exception as e:
        errors += 1
        print(f"{sid}: ERROR {type(e).__name__}: {str(e)[:200]}")
        continue

    for c in changes:
        rules[c.guard_name.split(" (")[0]] += 1

    for seg_id, truth in gt_status.items():
        raw = analysis.segment_verdicts[seg_id].status.value if seg_id in analysis.segment_verdicts else "missing"
        grd = guarded.segment_verdicts[seg_id].status.value if seg_id in guarded.segment_verdicts else "missing"
        if truth == "clear":
            clear_total += 1
            clear_to_uncertain += (grd == "uncertain")
        else:
            raw_c[raw if raw != truth else "correct"] += 1
            grd_c[grd if grd != truth else "correct"] += 1

n = sum(raw_c.values())
print(f"\nScenes with errors: {errors}")
print(f"Real BLOCKED/PARTIAL segments: {n}")
print(f"  RAW model     : {dict(raw_c)}   false-clear = {raw_c['clear']}/{n}")
print(f"  WITH GUARDS   : {dict(grd_c)}   false-clear = {grd_c['clear']}/{n}")
print(f"Real CLEAR segments turned UNCERTAIN by guards: {clear_to_uncertain}/{clear_total}")
print(f"Guard rules that fired (count of changes): {dict(rules)}")

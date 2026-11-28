"""List every real BLOCKED/PARTIAL segment and whether the model got it right.

Reads saved prediction and ground-truth files only. No API calls.
Development scenes only (synthetic data).
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions-dir", default="results/predictions/dev/gemini-v2-labelled-batch")
    ap.add_argument("--ground-truth-dir", default="datasets/v1")
    ap.add_argument("--output", default="results/predictions/dev/failure_cases_labelled_v2.csv")
    args = ap.parse_args()

    pred_dir = Path(args.predictions_dir)
    gt_dir = Path(args.ground_truth_dir)
    rows = []

    for gt_path in sorted(gt_dir.glob("S-*/ground_truth.json")):
        scene = gt_path.parent.name
        pred_path = pred_dir / f"{scene}_prediction.json"
        if not pred_path.exists():
            print(f"Missing prediction: {pred_path}")
            continue
        gt = load(gt_path)
        pred = load(pred_path)
        hazards = pred.get("hazards", [])
        hazard_types = ",".join(sorted({str(h.get("type")) for h in hazards}))
        verdicts = pred.get("segment_verdicts", {})

        for seg in gt.get("segment_statuses", []):
            true_status = str(seg.get("status")).upper()
            if true_status == "CLEAR":
                continue  # only real BLOCKED / PARTIAL segments matter here
            seg_id = seg.get("segment_id")
            v = verdicts.get(seg_id, {})
            pred_status = str(v.get("status", "missing")).upper()
            rows.append({
                "scene": scene,
                "segment": seg_id,
                "true_status": true_status,
                "true_max_coverage": seg.get("max_coverage"),
                "pred_status": pred_status,
                "pred_confidence": v.get("confidence"),
                "result": "OK" if pred_status == true_status else "WRONG",
                "hazards_found_in_scene": len(hazards),
                "hazard_types_found": hazard_types,
                "evidence": v.get("evidence"),
            })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{'scene':<8}{'segment':<9}{'true':<9}{'cover':>6}  {'pred':<9}{'conf':>5}  {'#haz':>4}  result")
    for r in rows:
        cov = r["true_max_coverage"]
        cov_txt = f"{cov:.2f}" if isinstance(cov, (int, float)) else "-"
        conf = r["pred_confidence"]
        conf_txt = f"{conf:.2f}" if isinstance(conf, (int, float)) else "-"
        print(f"{r['scene']:<8}{r['segment']:<9}{r['true_status']:<9}{cov_txt:>6}  "
              f"{r['pred_status']:<9}{conf_txt:>5}  {r['hazards_found_in_scene']:>4}  {r['result']}")

    print()
    print("Summary (real BLOCKED / PARTIAL segments only)")
    for status in ("BLOCKED", "PARTIAL"):
        subset = [r for r in rows if r["true_status"] == status]
        wrong = [r for r in subset if r["result"] == "WRONG"]
        print(f"  {status}: {len(subset)} total, {len(wrong)} wrong")
        print(f"    wrong, by what the model said: {dict(Counter(r['pred_status'] for r in wrong))}")
        no_haz = [r for r in wrong if r["hazards_found_in_scene"] == 0]
        print(f"    wrong in scenes where the model listed NO hazards: {len(no_haz)}")
    print(f"CSV saved to: {out}")


if __name__ == "__main__":
    main()

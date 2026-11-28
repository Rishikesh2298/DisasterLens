"""Print one comparison table from the saved DisasterLens eval reports.

Reads JSON files only. Makes no API calls and changes no files.
Results are on the 20 development scenes only (synthetic data).
"""
import json
import sys
from pathlib import Path

REPORT_DIR = Path("results/predictions/dev")

REPORTS = [
    ("always_clear", "eval_always_clear.json"),
    ("proximity", "eval_proximity.json"),
    ("noisy_oracle (mock)", "eval_noisy_oracle.json"),
    ("plain_v2", "eval_plain_v2.json"),
    ("labelled_v2", "eval_labelled_v2.json"),
]


def fmt(value):
    """Show a number with 4 decimals, or '-' when the value is missing."""
    if value is None:
        return "-"
    return f"{value:.4f}"


def load_row(name, filename):
    path = REPORT_DIR / filename
    if not path.exists():
        print(f"Missing report: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        report = json.load(f)

    overall = report["overall"]
    blocked = overall["per_class"]["BLOCKED"]
    matrix = overall["confusion_matrix"]

    # False-clear = a BLOCKED or PARTIAL segment predicted as CLEAR.
    non_clear_total = sum(sum(matrix[c].values()) for c in ("BLOCKED", "PARTIAL"))
    non_clear_called_clear = sum(matrix[c]["CLEAR"] for c in ("BLOCKED", "PARTIAL"))
    false_clear = non_clear_called_clear / non_clear_total if non_clear_total else None

    return (
        name,
        overall["overall_accuracy"],
        overall["macro_f1"],
        blocked["recall"],
        blocked["precision"],
        false_clear,
        overall["uncertain_rate"],
    )


def main():
    headers = ("Setup", "Accuracy", "MacroF1", "BlkRecall", "BlkPrec", "FalseClear", "UncertRate")
    print("DisasterLens - 20 development scenes, synthetic data only (not a held-out test)")
    print()
    print(f"{headers[0]:<22}" + "".join(f"{h:>12}" for h in headers[1:]))
    print("-" * (22 + 12 * 6))
    for name, filename in REPORTS:
        row = load_row(name, filename)
        print(f"{row[0]:<22}" + "".join(f"{fmt(v):>12}" for v in row[1:]))
    print()
    print("FalseClear = share of real BLOCKED/PARTIAL segments predicted CLEAR (lower is better).")


if __name__ == "__main__":
    main()

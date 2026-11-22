"""Validate JSON fixtures against the shared Pydantic contracts."""

import argparse
from pathlib import Path

from dl.contracts.evaluation import (
    EvaluationDataset,
    EvaluationPredictionFile,
    EvaluationSummary,
)


def validate_fixtures(directory: Path):
    checked = 0
    for path in sorted(directory.rglob("*.json")):
        content = path.read_text(encoding="utf-8")
        if path.name.endswith(".summary.json"):
            EvaluationSummary.model_validate_json(content)
        elif path.name.endswith("_dataset.json"):
            EvaluationDataset.model_validate_json(content)
        elif path.name.endswith("_predictions.json"):
            EvaluationPredictionFile.model_validate_json(content)
        else:
            raise ValueError(f"Fixture has no registered contract: {path}")
        checked += 1
    if not checked:
        raise ValueError(f"No recognized JSON contract fixtures found in {directory}")
    return checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("fixtures"))
    args = parser.parse_args(argv)
    count = validate_fixtures(args.directory)
    print(f"Validated {count} contract fixture(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

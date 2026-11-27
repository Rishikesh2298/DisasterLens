"""
scripts/smoke_test.py
---------------------
Real / mock smoke test script for Gemini Vision AI engine on DisasterLens scenes.

Usage:
    # Live mode (requires GEMINI_API_KEY environment variable):
    python scripts/smoke_test.py --variant plain
    python scripts/smoke_test.py --variant labelled

    # Mock mode (offline test without API key):
    python scripts/smoke_test.py --variant plain --mode mock
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import dl.vision.providers.gemini  # noqa: F401 (trigger adapter registration)
from dl.vision.api import analyze_observation
from dl.vision.runner import SceneLoader


def run_smoke_test(
    scene_id: str = "S-0001",
    dataset_dir: str = "datasets/v1",
    image_variant: str = "plain",
    model: str = "gemini-3.8-flash",
    prompt_version: str = "v1",
    mode: str = "live",
) -> None:
    scene_path = _REPO_ROOT / dataset_dir / scene_id
    if not scene_path.exists():
        print(f"Error: Scene folder not found at {scene_path}", file=sys.stderr)
        sys.exit(1)

    image_path = scene_path / f"image_{image_variant}.png"
    if not image_path.exists():
        print(f"Error: Image not found at {image_path}", file=sys.stderr)
        sys.exit(1)

    if mode == "live" and not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print(
            "ERROR: GEMINI_API_KEY environment variable is not set.\n"
            "Please configure GEMINI_API_KEY before running live mode:\n"
            '  $env:GEMINI_API_KEY = "your-api-key"\n'
            "Or run in mock mode to verify the pipeline offline:\n"
            "  python scripts/smoke_test.py --mode mock",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading scene {scene_id} from {scene_path}...")
    loader = SceneLoader(scene_path)
    scene = loader.load_scene()
    print(f"Loaded scene {scene.scene_id} with {len(scene.segments)} road segments.")

    print(f"Executing analyze_observation(mode='{mode}', model='{model}', variant='{image_variant}')...")
    result = analyze_observation(
        image=image_path,
        zone_geometry=scene,
        mode=mode,
        provider="gemini",
        model=model,
        prompt_version=prompt_version,
        image_variant=image_variant,
    )

    print("\n" + "=" * 50)
    print(f"=== Smoke Test Result: {scene_id} ({image_variant}) ===")
    print("=" * 50)
    print(f"Model ID:        {result.model_id}")
    print(f"Prompt Version:  {result.prompt_version}")
    print(f"Latency (ms):    {result.latency_ms}")
    print(f"Hazards Found:   {len(result.hazards)}")
    for h in result.hazards:
        bbox_coords = list(h.bbox.root) if hasattr(h.bbox, "root") else list(h.bbox)
        print(f"  - [{h.hazard_type.value}] conf={h.confidence:.2f} bbox={bbox_coords}: {h.description}")

    print(f"\nGuarded Verdicts ({len(result.guarded_verdicts)} segments):")
    for seg_id, verdict in sorted(result.guarded_verdicts.items()):
        print(f"  - {seg_id}: {verdict.status.value:<18} (conf={verdict.confidence:.2f}, visible={verdict.visible})")
    print("=" * 50 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="DisasterLens Vision AI Smoke Test")
    parser.add_argument("--scene", default="S-0001", help="Scene ID (default: S-0001)")
    parser.add_argument("--dataset", default="datasets/v1", help="Dataset directory (default: datasets/v1)")
    parser.add_argument(
        "--variant",
        choices=["plain", "labelled"],
        default="plain",
        help="Image variant (default: plain)",
    )
    parser.add_argument("--model", default="gemini-3.8-flash", help="Model name (default: gemini-3.8-flash)")
    parser.add_argument("--prompt-version", default="v1", help="Prompt version (default: v1)")
    parser.add_argument(
        "--mode",
        choices=["live", "mock"],
        default="live",
        help="Execution mode: 'live' or 'mock' (default: live)",
    )

    args = parser.parse_args()
    run_smoke_test(
        scene_id=args.scene,
        dataset_dir=args.dataset,
        image_variant=args.variant,
        model=args.model,
        prompt_version=args.prompt_version,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()

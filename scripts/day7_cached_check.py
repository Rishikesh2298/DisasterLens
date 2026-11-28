"""Day 7 prep: cached mode via analyze_observation, no key, temp copies of the caches."""
import os, shutil, tempfile
from pathlib import Path

for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(k, None)
os.environ["VISION_PROVIDER"] = "gemini"
os.environ["VISION_MODEL"] = "gemini-3.5-flash-lite"

from dl.vision.api import analyze_observation
from dl.vision.runner import SceneLoader

base = Path("results/predictions/dev")
tmp_root = Path(tempfile.mkdtemp())
for variant, batch in (("labelled", "gemini-v2-labelled-batch"), ("plain", "gemini-v2-plain-batch")):
    cache_copy = tmp_root / variant
    shutil.copytree(base / batch / ".cache", cache_copy)
    hits, misses, models = 0, 0, set()
    for sd in sorted(Path("datasets/v1").glob("S-*")):
        ld = SceneLoader(sd, split="dev")
        try:
            r = analyze_observation(ld.load_image(variant), ld.load_scene(), mode="cached",
                                    prompt_version="v2", image_variant=variant, cache_dir=cache_copy)
            hits += 1
            models.add(r.model_id)
        except Exception as e:
            misses += 1
            print(f"  {variant} {sd.name}: {type(e).__name__}: {str(e)[:100]}")
    print(f"{variant}: hits={hits} misses={misses} model_ids={models}")
shutil.rmtree(tmp_root, ignore_errors=True)

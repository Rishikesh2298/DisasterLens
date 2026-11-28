"""Day 6: replay saved Gemini cache offline. Uses a TEMP COPY of the cache. No API calls."""
import json, os, shutil, tempfile
from pathlib import Path

for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(k, None)

from dl.vision.api import analyze_observation
from dl.vision.runner import SceneLoader

PRED = Path("results/predictions/dev/gemini-v2-labelled-batch")
SRC_CACHE = PRED / ".cache"
tmp = Path(tempfile.mkdtemp()) / "cache_copy"
shutil.copytree(SRC_CACHE, tmp)

first = json.loads((PRED / "S-0001_prediction.json").read_text(encoding="utf-8"))
MODEL_ID = first["model_id"]
print("model_id used for the key:", MODEL_ID)


class NoCallAdapter:
    model_id = MODEL_ID
    def analyze_scene(self, **kwargs):
        raise RuntimeError("CACHE MISS - inner adapter was called")


hits = misses = 0
for scene_dir in sorted(Path("datasets/v1").glob("S-*")):
    loader = SceneLoader(scene_dir, split="dev")
    try:
        r = analyze_observation(loader.load_image("labelled"), loader.load_scene(), mode="cached",
                                prompt_version="v2", inner_adapter=NoCallAdapter(), cache_dir=tmp)
        hits += 1
    except RuntimeError:
        misses += 1
        print(scene_dir.name, "-> MISS")
print(f"cache hits: {hits}   misses: {misses}")
shutil.rmtree(tmp.parent, ignore_errors=True)

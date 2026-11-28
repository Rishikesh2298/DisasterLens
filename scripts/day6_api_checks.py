"""Day 6 offline checks for dl.vision.api.analyze_observation. No API calls."""
import os
from collections import Counter
from pathlib import Path

for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(k, None)   # make sure nothing can reach the real API

from dl.vision.api import analyze_observation
from dl.vision.runner import SceneLoader

loader = SceneLoader(Path("datasets/v1/S-0001"), split="dev")
scene = loader.load_scene()
img = loader.load_image("plain")


def check(name, fn):
    try:
        out = fn()
        print(f"[OK   ] {name}: {out}")
    except Exception as e:  # we want to see every error type
        print(f"[RAISE] {name}: {type(e).__name__}: {str(e)[:160]}")


def mock_normal():
    r = analyze_observation(img, scene, mode="mock", prompt_version="v2")
    return (f"model={r.model_id} hazards={len(r.hazards)} "
            f"verdicts={dict(Counter(str(v.status) for v in r.guarded_verdicts.values()))}")


class FailingAdapter:
    def analyze_scene(self, **kwargs):
        raise RuntimeError("simulated API failure")


check("1 mock, normal image", mock_normal)
check("2 empty image bytes", lambda: analyze_observation(b"", scene, mode="mock"))
check("3 garbage bytes (not an image), mock",
      lambda: len(analyze_observation(b"this is not an image", scene, mode="mock").guarded_verdicts))
check("4 missing image file", lambda: analyze_observation("nope.png", scene, mode="mock"))
check("5 wrong mode", lambda: analyze_observation(img, scene, mode="banana"))
check("6 live mode, no key, no adapter",
      lambda: analyze_observation(img, scene, mode="live", prompt_version="v2"))
check("7 live mode, API raises error",
      lambda: analyze_observation(img, scene, mode="live", adapter=FailingAdapter()))
check("8 zone_geometry as Path (handoff doc example)",
      lambda: analyze_observation(img, Path("datasets/v1/S-0001"), mode="mock"))

cache_dir = "results/predictions/dev/gemini-v2-labelled-batch/.cache"
labelled = loader.load_image("labelled")
check("9 cached, saved cache, no key",
      lambda: len(analyze_observation(labelled, scene, mode="cached", prompt_version="v2",
                                      image_variant="labelled", cache_dir=cache_dir).guarded_verdicts))
check("10 cached with provider='gemini' (handoff doc example)",
      lambda: len(analyze_observation(labelled, scene, mode="cached", prompt_version="v2",
                                      provider="gemini", cache_dir=cache_dir).guarded_verdicts))

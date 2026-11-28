# Vision AI Notes (Day 5)

**Synthetic scenes only. These results do not describe real disaster performance. This is a research prototype, not a safety system.**

## 1. What was evaluated

- Scenes: the 20 development scenes S-0001 to S-0020 (480 road segments: 436 CLEAR, 35 BLOCKED, 9 PARTIAL).
- There is no separate test set. The S-0031 to S-0100 scenes were not generated (confirmed with Tejash). So there is **no held-out test result**. These 20 scenes were also used to tune Prompt v2 and to choose the labelled variant, so all numbers below are probably **optimistic**.
- Model: Gemini, `gemini-3.5-flash-lite`. Prompt v2 plain and labelled, frozen. SHA-256 checksums were re-checked on Day 5 and match `docs/prompt-v2-freeze.md`.
- Validity: 20/20 valid prediction files for each variant.
- No new model calls were made on Day 5. The saved predictions were evaluated offline with `scripts/evaluate_predictions.py`.

## 2. Results (20 development scenes)

| Setup | Accuracy | BLOCKED recall | BLOCKED precision | False-clear rate |
|---|---:|---:|---:|---:|
| always_clear (baseline) | 0.9083 | 0.0000 | - | 1.0000 |
| proximity (baseline) | 0.9708 | 1.0000 | 0.7143 | 0.0000 |
| noisy_oracle (baseline, MOCK) | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| Plain v2 (Gemini) | 0.8833 | 0.0286 | 0.0714 | 0.9318 |
| Labelled v2 (Gemini) | 0.9354 | 0.3714 | 1.0000 | 0.6591 |

False-clear rate = share of real BLOCKED or PARTIAL segments predicted CLEAR (lower is better). Labelled v2: 29 of 44. Plain v2: 41 of 44.

## 3. How to read the results

- **Do not rank setups by macro F1.** The evaluator leaves out classes with no defined F1 (for example PARTIAL), so macro F1 is not comparable between rows. Use BLOCKED recall and the false-clear rate.
- **Accuracy hides the problem.** 436 of 480 segments are CLEAR, so always_clear scores 0.9083. Labelled v2 beats it by only about 2.7 points. Plain v2 is below it.
- **Labelled v2 is clearly better than Plain v2** on BLOCKED recall (0.3714 vs 0.0286) and false-clear rate (0.6591 vs 0.9318). It never called a road BLOCKED by mistake (precision 1.0), but it still misses most real obstructions.
- **The proximity baseline is not a vision model.** It reads the known hazard positions from the scene layout and does not look at the image. It is a reference for the "near is not blocked" mistake (it called 14 non-blocked segments BLOCKED), not a fair vision comparison.
- **noisy_oracle is a mock.** It reads the ground truth. Its default noise rates are 0.0 and the run log does not record the rates, so the perfect score is consistent with zero noise. Treat it as an upper bound, not a model result.

## 4. Failure analysis (Labelled v2)

Full list: `results/predictions/dev/failure_cases_labelled_v2.csv` (made by `scripts/list_failure_cases.py`).

- BLOCKED: 35 real, 13 found, 22 missed (20 called CLEAR, 2 called PARTIAL).
- PARTIAL: 9 real, 0 found, all 9 called CLEAR (coverage 0.37 to 0.75).
- 15 of the 31 wrong segments were CLEAR calls in scenes where the model listed no hazards at all (S-0003, S-0010, S-0016, S-0017, S-0018). In these scenes the hazard was not detected.
- 14 wrong segments were CLEAR calls in scenes where the model did list hazards, but the verdict for the segment did not use them.
- Confidence does not separate right from wrong. Wrong answers carry 0.85 (one 0.80), the same as correct ones. Confidence is not a useful signal here.

## 5. Limits

- Development scenes only; optimistic; no held-out test.
- Synthetic images only.
- The evaluator counts UNCERTAIN as wrong because UNCERTAIN is not a ground-truth class. It cannot show the benefit of guards. The false-clear rate is the fairer measure for that.
- Hazard bounding-box metrics are not computed (ground truth has no hazard coordinates).

## 6. Open items for Day 6

- Confirm whether the evaluated predictions are before or after the guards. The model never said UNCERTAIN, although 15 CLEAR calls had no hazard list.
- Confirm that `analyze_observation` applies the guards and the mapper (a CLEAR verdict with 30% or more mapped overlap becomes UNCERTAIN).
- Prompt v2 stays frozen. No prompt was changed using these results.

## 7. Guarded results (Day 6, Labelled v2, 20 development scenes)

The saved predictions in section 2 are raw model output, before the guards. On Day 6 the mapper and guards were applied offline to the same 20 saved predictions (`scripts/day6_guarded_eval.py`, no API calls).

| | Raw model | With guards |
|---|---:|---:|
| Real BLOCKED/PARTIAL segments called CLEAR | 29 of 44 (0.6591) | 25 of 44 (0.5682) |
| Real BLOCKED/PARTIAL segments called UNCERTAIN | 0 | 4 |
| Real CLEAR segments turned UNCERTAIN | - | 4 of 436 |

- Only Guard Rule 2 (model CLEAR, mapper overlap of 30% or more) fired: 8 changes in total. Rules 1 and 3 did not fire.
- The guards reduce the false-clear rate a little, but more than half of real obstructions are still called CLEAR.
- 15 of the false-clear segments are in scenes where the model listed no hazards. Guard Rule 1 did not change them. Reading `guards.py`, an empty hazard list appears to count as "a hazard list was produced"; this was not tested directly.
- Design question for the team (not changed): should a CLEAR verdict with an empty hazard list become UNCERTAIN? Guards were not modified on Day 6.
- Development scenes only; optimistic; synthetic data.

## 8. Day 6 integration checks (offline, no API calls)

Checked with `scripts/day6_api_checks.py` and `scripts/day6_cached_offline.py`.

- Bad input to `analyze_observation`: empty image bytes, a missing image file and an invalid mode give clear errors (`ValueError`, `FileNotFoundError`). Garbage bytes (not an image) are accepted, because the function does not inspect the image; the mock adapter ignores it. Behaviour of the real Gemini adapter on a bad image was not tested (it needs an API call).
- API failure: an error raised by the adapter passes up as-is (`RuntimeError` in the test). There is no automatic fallback to cached or mock mode, so the backend endpoint must catch the error and switch mode.
- Cached mode offline: all 20 saved Labelled v2 Gemini responses were replayed from a temporary copy of the cache with no API key and a fake inner adapter that fails if called. Result: 20 cache hits, 0 misses.
- Missing timestamp: `analyze_observation` takes no timestamp. This test belongs to the backend upload endpoint and was not run here.
- Two bugs found and fixed in `dl/vision/api.py` (Day 7): (1) `analyze_observation` checked the registered providers before the Gemini module was loaded, so `mode="live"` raised a false `NotImplementedError` ("gemini.py is empty"). It now loads the provider first; live mode without a key gives the "GEMINI_API_KEY ... not configured" error. (2) `mode="cached"` silently used the mock adapter. It now loads the provider from `provider=` or `VISION_PROVIDER`. After both fixes: 206 tests pass, and the Labelled v2 and Plain v2 caches both replay with 20 hits, 0 misses and model id `gemini-3.5-flash-lite` (temporary copies, no API key, `scripts/day7_cached_check.py`). The batch runner was never affected.
- Cache key: it uses model id, prompt version, scene id and image bytes. The roadmap describes model + prompt hash + image hash.

## 9. Backend integration status (Day 6, read-only check of Rajneesh's branch)

Checked `origin/feat/rajneesh/backend-foundation` (commit 8cf3f5d) without changing any file.

- `POST /api/observations` does NOT call `analyze_observation` (0 call sites). It uses a stub in `dl/vision/provider.py`; cached and live mode raise errors there.
- His branch does not contain `dl/vision/api.py`, `guards.py`, `mapper.py` or the Prompt v2 files.
- His router builds no `zone_geometry`, which `analyze_observation` needs.
- Bad-image and missing-timestamp checks are done in his upload route and covered by his tests (`test_23` to `test_29`). The timestamp is required and is not passed to the vision function.
- No test for a vision failure or cached mode exists on his side yet.
- Status casing differs between his contract (uppercase) and the vision contract (lowercase). Default `VISION_MODEL` on his side is `gemini-1.5-flash`.
- Result: the end-to-end test of `analyze_observation` through the backend could not be run on Day 6. It is open for Day 7 and depends on the integration above.

## 10. Day 7 checks (offline, no API calls)

- Fixes in `dl/vision/api.py` (live-mode and cached-mode provider loading): see section 8. After them, 206 tests pass.
- Cached replay of both caches (temporary copies, no API key, `scripts/day7_cached_check.py`): Labelled v2 and Plain v2 both gave 20 hits, 0 misses, model id `gemini-3.5-flash-lite`. A second run that passes `provider="gemini"` directly (instead of the `VISION_PROVIDER` variable) gave the same result.
- Cache freeze (SHA-256 over the per-file hashes, files sorted by path), recorded on 28 Nov 2026:
  - `results/predictions/dev/gemini-v2-labelled-batch/.cache`: 20 files, fingerprint `98D0EEA23D3E2163D5670D9A858796D76B18AEBB9C93080AE518CF4746BB1225`
  - `results/predictions/dev/gemini-v2-plain-batch/.cache`: 20 files, fingerprint `1F739FB4976F6DEAFC76E74A507D5AA8CB167AF01CEF7E480BE2D02F8EDA7FB3`
- Cache location: the roadmap names `results/cache`, which is the default folder in `dl/vision/cache.py`. The saved Gemini responses live inside each batch folder instead. No script in `scripts/` reads `results/cache`. The files were not moved, so the verified replay stays valid.
- Secrets check: a search of tracked and non-ignored files for key-like text found one match, a dummy `fake_key` value in `tests/test_vision_parser.py`. No `.env` file is tracked or present. Key values were never printed.
- Handoff document `docs/analyze-observation-api-handoff.md`: the cached example now uses a real cache folder and `image_variant`.
- Not done: mock-mode and cached-mode checks on the live site. They need Rajneesh's upload endpoint to call `analyze_observation` (see section 9).
- All results are on the 20 development scenes only, so they are optimistic. There is no held-out test set. This is a synthetic-data research prototype, not a safety system.

## 11. Cache freeze copy in results/cache (Day 7)

- To follow the roadmap folder (`results/cache`), the two Gemini caches were copied (originals left in place and unchanged):
  - `results/cache/gemini-v2-labelled`: 20 files, fingerprint `98D0EEA23D3E2163D5670D9A858796D76B18AEBB9C93080AE518CF4746BB1225` (identical to the original)
  - `results/cache/gemini-v2-plain`: 20 files, fingerprint `1F739FB4976F6DEAFC76E74A507D5AA8CB167AF01CEF7E480BE2D02F8EDA7FB3` (identical to the original)
- Fingerprint = SHA-256 over the per-file SHA-256 hashes, files sorted by path. A replay from the copies was not run; the identical fingerprints show the files match.
- Still open: mock-mode and cached-mode checks on the live site (need the backend endpoint to call `analyze_observation`), and team rehearsals.

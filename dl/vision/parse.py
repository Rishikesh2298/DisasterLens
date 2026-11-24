import json
import re
from typing import Callable

from pydantic import ValidationError

from dl.contracts.vision import SceneAnalysis

# Type alias for repair callback: receives (raw_text, error_description) and returns repaired_text
RepairCallback = Callable[[str, str], str]


def _extract_outermost_object(text: str, start: int) -> str:
    """
    Extract the outermost JSON object from `text` starting at position `start`
    (which must be the index of an opening `{`).

    Uses bracket counting while correctly skipping over:
    - Characters inside double-quoted strings (including escaped quotes).
    - Braces that appear as values inside strings.

    Returns:
        The full JSON object substring (inclusive of opening and closing braces).

    Raises:
        ValueError: If no matching closing brace is found.
    """
    depth = 0
    in_string = False
    i = start

    while i < len(text):
        ch = text[i]

        if in_string:
            if ch == "\\" and i + 1 < len(text):
                i += 2  # Skip the escaped character
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        i += 1

    raise ValueError(
        f"No matching closing brace found for opening brace at position {start}."
    )


def extract_json_string(text: str) -> str:
    """
    Extract a JSON object string from raw model text.

    Handles all of the following correctly:
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Conversational preamble and postamble text
    - Deeply nested JSON objects (segment_verdicts, hazards, etc.)
    - Curly braces appearing inside JSON string values

    Uses a bracket-counter to locate the exact outermost `{...}` boundary
    rather than a non-greedy regex that stops at the first closing brace.

    Raises:
        ValueError: If no JSON object structure can be found in the text.
    """
    if not text or not text.strip():
        raise ValueError("Empty or whitespace-only response text.")

    # Strip fenced code block markers to get the inner content region to scan
    fence_pattern = re.compile(r"```(?:json)?[ \t]*\n?([\s\S]*?)```", re.IGNORECASE)
    fence_match = fence_pattern.search(text)
    search_text = fence_match.group(1) if fence_match else text

    # Find the first opening brace within the region
    first_brace = search_text.find("{")
    if first_brace == -1:
        raise ValueError("No JSON object structure found in response text.")

    return _extract_outermost_object(search_text, first_brace).strip()


def _parse_and_validate(
    raw_text: str,
    scene_id: str,
    model_id: str,
    prompt_version: str,
    latency_ms: int | None = None,
) -> SceneAnalysis:
    """
    Extract, parse, and validate a JSON string into SceneAnalysis.

    Raises:
        ValueError, json.JSONDecodeError, ValidationError on any failure.
    """
    json_str = extract_json_string(raw_text)
    data = json.loads(json_str)

    if not isinstance(data, dict):
        raise ValueError(f"Root JSON must be an object/dict, got {type(data).__name__}")

    # Inject required metadata if omitted by model in the raw payload
    if "scene_id" not in data:
        data["scene_id"] = scene_id
    if "model_id" not in data:
        data["model_id"] = model_id
    if "prompt_version" not in data:
        data["prompt_version"] = prompt_version
    if latency_ms is not None and "latency_ms" not in data:
        data["latency_ms"] = latency_ms

    # Optional graceful clamping for segment confidence:
    # If a model emits 0.85 < confidence <= 1.0, clamp to 0.85 to respect
    # the existing SegmentVerdict schema constraint without rejecting valid reasoning.
    if "segment_verdicts" in data and isinstance(data["segment_verdicts"], dict):
        for seg_data in data["segment_verdicts"].values():
            if isinstance(seg_data, dict) and "confidence" in seg_data:
                conf = seg_data["confidence"]
                if isinstance(conf, (int, float)) and 0.85 < conf <= 1.0:
                    seg_data["confidence"] = 0.85

    # Strictly validate against Pydantic SceneAnalysis contract
    return SceneAnalysis.model_validate(data)


def parse_scene_analysis(
    raw_text: str,
    scene_id: str,
    model_id: str,
    prompt_version: str = "v1",
    latency_ms: int | None = None,
    repair_callback: RepairCallback | None = None,
) -> SceneAnalysis:
    """
    Parse and validate raw model output into a validated SceneAnalysis object.

    Executes up to one repair retry via `repair_callback` if initial extraction
    or Pydantic validation fails. If parsing still fails, returns a fallback
    `SceneAnalysis` with `valid_json=False`.

    Args:
        raw_text: The raw string generated by the vision model.
        scene_id: Unique scene identifier (e.g. 'S-0001').
        model_id: Model identifier (e.g. 'gemini-1.5-pro').
        prompt_version: Prompt version used (e.g. 'v1', 'v2').
        latency_ms: Optional latency measurement in milliseconds.
        repair_callback: Optional callable(raw_text, error_msg) -> repaired_text
                         used to request exactly one repair from the provider.

    Returns:
        SceneAnalysis: Validated contract object. If parsing or validation fails,
                       `valid_json` is False and verdicts/hazards are empty.
    """
    # First parsing and validation attempt
    try:
        analysis = _parse_and_validate(
            raw_text=raw_text,
            scene_id=scene_id,
            model_id=model_id,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
        )
        analysis.valid_json = True
        return analysis
    except (ValueError, json.JSONDecodeError, ValidationError) as initial_error:
        error_msg = f"{type(initial_error).__name__}: {initial_error}"

    # One repair retry attempt if callback is provided
    if repair_callback is not None:
        try:
            repaired_text = repair_callback(raw_text, error_msg)
            repaired_analysis = _parse_and_validate(
                raw_text=repaired_text,
                scene_id=scene_id,
                model_id=model_id,
                prompt_version=prompt_version,
                latency_ms=latency_ms,
            )
            repaired_analysis.valid_json = True
            return repaired_analysis
        except (ValueError, json.JSONDecodeError, ValidationError):
            pass

    # Fallback response when validation fails
    # Never invent valid road verdicts or hazards for invalid outputs
    return SceneAnalysis(
        scene_id=scene_id,
        hazards=[],
        segment_verdicts={},
        damaged_building_count=None,
        water_regions=[],
        image_quality_good=None,
        model_id=model_id,
        prompt_version=prompt_version,
        valid_json=False,
        latency_ms=latency_ms,
    )

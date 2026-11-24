import dl.vision.parse as p
from dl.contracts.enums import RoadStatus

SCENE_ID = "S-0001"
MODEL_ID = "gemini-1.5-pro"
PROMPT_VERSION = "v1"


# ───────────────── Original 8 tests ─────────────────

def test_valid_json():
    raw = '{"hazards": [], "segment_verdicts": {"SEG-001": {"status": "clear", "confidence": 0.85}}}'
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is True
    assert res.scene_id == SCENE_ID
    assert res.model_id == MODEL_ID
    assert res.segment_verdicts["SEG-001"].status == RoadStatus.CLEAR
    assert res.segment_verdicts["SEG-001"].confidence == 0.85


def test_json_inside_extra_text():
    raw = (
        "Here is the vision AI analysis of the scene:\n"
        '{"hazards": [], "segment_verdicts": {"SEG-001": {"status": "blocked", "confidence": 0.85}}}\n'
        "Hope this assessment helps emergency responders."
    )
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is True
    assert res.segment_verdicts["SEG-001"].status == RoadStatus.BLOCKED


def test_json_inside_markdown_fences():
    raw = (
        "```json\n"
        '{\n  "hazards": [],\n  "segment_verdicts": {"SEG-001": {"status": "partial", "confidence": 0.5}}\n}\n'
        "```"
    )
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is True
    assert res.segment_verdicts["SEG-001"].status == RoadStatus.PARTIAL


def test_malformed_json():
    raw = '```json\n{"hazards": [broken json syntax...\n```'
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is False
    assert len(res.segment_verdicts) == 0
    assert len(res.hazards) == 0
    assert res.scene_id == SCENE_ID


def test_missing_fields():
    # Hazard is missing required bbox field
    raw = '{"hazards": [{"type": "flood", "confidence": 0.9}]}'
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is False
    assert len(res.hazards) == 0


def test_wrong_data_types():
    # hazards should be a list, not string
    raw = '{"hazards": "invalid_string_type"}'
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is False
    assert len(res.hazards) == 0


def test_successful_repair_retry():
    call_count = 0

    def mock_repair(raw: str, err: str) -> str:
        nonlocal call_count
        call_count += 1
        return '{"hazards": [], "segment_verdicts": {"SEG-001": {"status": "clear", "confidence": 0.85}}}'

    raw_broken = "{unclosed broken json"
    res = p.parse_scene_analysis(
        raw_broken, SCENE_ID, MODEL_ID, PROMPT_VERSION, repair_callback=mock_repair
    )
    assert call_count == 1
    assert res.valid_json is True
    assert res.segment_verdicts["SEG-001"].status == RoadStatus.CLEAR


def test_failed_repair_retry():
    call_count = 0

    def mock_repair(raw: str, err: str) -> str:
        nonlocal call_count
        call_count += 1
        return "{still broken after repair"

    raw_broken = "{unclosed broken json"
    res = p.parse_scene_analysis(
        raw_broken, SCENE_ID, MODEL_ID, PROMPT_VERSION, repair_callback=mock_repair
    )
    assert call_count == 1
    assert res.valid_json is False
    assert len(res.segment_verdicts) == 0


# ───────────────── New nested JSON tests ─────────────────

def test_nested_segment_verdicts_unfenced():
    """Deeply nested JSON with multiple segment verdicts must all be extracted correctly."""
    raw = (
        "Analysis complete.\n"
        '{"hazards": [{"type": "flood", "bbox": [10, 20, 50, 60], "confidence": 0.9}], '
        '"segment_verdicts": {'
        '"SEG-001": {"status": "blocked", "confidence": 0.85, "evidence": "Flood covers road"}, '
        '"SEG-002": {"status": "clear", "confidence": 0.7, "evidence": "No obstruction detected"}, '
        '"SEG-003": {"status": "partial", "confidence": 0.6, "evidence": "Debris on edge"}'
        '}, "damaged_building_count": 2}\n'
        "End of response."
    )
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is True
    assert len(res.segment_verdicts) == 3
    assert res.segment_verdicts["SEG-001"].status == RoadStatus.BLOCKED
    assert res.segment_verdicts["SEG-002"].status == RoadStatus.CLEAR
    assert res.segment_verdicts["SEG-003"].status == RoadStatus.PARTIAL
    assert len(res.hazards) == 1
    assert res.damaged_building_count == 2


def test_nested_segment_verdicts_fenced():
    """Deeply nested JSON inside Markdown fences must be fully extracted."""
    raw = (
        "Here is my output:\n"
        "```json\n"
        "{\n"
        '  "hazards": [{"type": "debris", "bbox": [0, 0, 100, 100], "confidence": 0.8}],\n'
        '  "segment_verdicts": {\n'
        '    "SEG-010": {"status": "blocked", "confidence": 0.85, "evidence": "Debris blocks road"},\n'
        '    "SEG-011": {"status": "uncertain", "confidence": 0.4, "evidence": "Partial visibility"}\n'
        "  },\n"
        '  "image_quality_good": true\n'
        "}\n"
        "```\n"
        "Let me know if you need more."
    )
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is True
    assert len(res.segment_verdicts) == 2
    assert res.segment_verdicts["SEG-010"].status == RoadStatus.BLOCKED
    assert res.segment_verdicts["SEG-011"].status == RoadStatus.UNCERTAIN
    assert res.image_quality_good is True


def test_braces_inside_string_values():
    """Curly braces that appear inside JSON string values must not break extraction."""
    raw = (
        '{"hazards": [], '
        '"segment_verdicts": {'
        '"SEG-005": {"status": "clear", "confidence": 0.7, "evidence": "Road visible {no obstructions found}"}'
        "}}"
    )
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is True
    assert res.segment_verdicts["SEG-005"].status == RoadStatus.CLEAR
    assert "{no obstructions found}" in res.segment_verdicts["SEG-005"].evidence


def test_escaped_quotes_and_braces_in_evidence():
    """
    Evidence strings containing escaped double-quotes AND curly braces must be
    extracted fully. The bracket-counter must skip braces inside quoted strings,
    and the JSON parser must correctly interpret escaped quotes inside strings.

    Raw evidence: The sign says \"flood {warning}\" near the road.
    """
    # Build the raw response: conversational preamble + JSON + postamble
    raw = (
        "The model found:\n"
        '{"hazards": [], '
        '"segment_verdicts": {'
        '"SEG-007": {'
        '"status": "blocked", '
        '"confidence": 0.85, '
        r'"evidence": "The sign says \"flood {warning}\" near the road."'
        "}"
        "}"
        "}\n"
        "End of response."
    )

    # 1. Verify extract_json_string returns the COMPLETE nested object
    extracted = p.extract_json_string(raw)
    assert extracted.startswith("{"), "Extracted JSON must start with '{'"
    assert extracted.endswith("}"), "Extracted JSON must end with '}'"
    assert "SEG-007" in extracted, "Extracted JSON must contain nested segment_verdicts key"
    assert "flood {warning}" in extracted, "Extracted JSON must preserve braces inside string value"

    # 2. Verify full parse succeeds with valid_json=True and evidence intact
    res = p.parse_scene_analysis(raw, SCENE_ID, MODEL_ID, PROMPT_VERSION)
    assert res.valid_json is True
    assert res.segment_verdicts["SEG-007"].status == RoadStatus.BLOCKED
    assert 'flood {warning}' in res.segment_verdicts["SEG-007"].evidence


# ───────────────── Runner ─────────────────

if __name__ == "__main__":
    tests = [
        (test_valid_json,                           "Test  1 Passed: Valid JSON"),
        (test_json_inside_extra_text,               "Test  2 Passed: JSON inside extra text"),
        (test_json_inside_markdown_fences,          "Test  3 Passed: JSON inside Markdown fences"),
        (test_malformed_json,                       "Test  4 Passed: Malformed JSON"),
        (test_missing_fields,                       "Test  5 Passed: Missing fields"),
        (test_wrong_data_types,                     "Test  6 Passed: Wrong data types"),
        (test_successful_repair_retry,              "Test  7 Passed: Successful repair retry"),
        (test_failed_repair_retry,                  "Test  8 Passed: Failed repair retry"),
        (test_nested_segment_verdicts_unfenced,     "Test  9 Passed: Nested segment_verdicts (unfenced)"),
        (test_nested_segment_verdicts_fenced,       "Test 10 Passed: Nested segment_verdicts (fenced)"),
        (test_braces_inside_string_values,          "Test 11 Passed: Braces inside string values"),
        (test_escaped_quotes_and_braces_in_evidence,"Test 12 Passed: Escaped quotes + braces in evidence"),
    ]
    for fn, label in tests:
        fn()
        print(label)
    print("\nALL 12 PARSER TESTS PASSED SUCCESSFULLY!")

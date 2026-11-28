import pytest
from pydantic import ValidationError

from dl.contracts.scene import Box
from dl.contracts.vision import SegmentVerdict
from dl.evaluation.calibration import score_calibration
from dl.evaluation.matching import box_iou, greedy_match
from dl.evaluation.metrics import classification_scores, prf
from dl.evaluation.route_impact import score_route_impact
from dl.evaluation.run import evaluate, load_prediction_metadata, load_scenes, select_split


def test_hand_calculated_prf_and_zero_denominators():
    result = prf(2, 1, 2)
    assert result["tp"] == 2 and result["fp"] == 1 and result["fn"] == 2
    assert result["precision"] == 2 / 3 and result["recall"] == 0.5
    assert result["f1"] == pytest.approx(4 / 7)
    assert prf(0, 0, 0)["f1"] == 0


def test_box_iou_and_confidence_ordered_matching():
    assert box_iou([0, 0, 2, 2], [1, 1, 3, 3]) == 1 / 7
    result = greedy_match(
        [{"type": "flood", "bbox": [0, 0, 10, 10]}],
        [
            {"type": "flood", "bbox": [0, 0, 10, 10], "confidence": 0.2},
            {"type": "flood", "bbox": [0, 0, 10, 10], "confidence": 0.9},
        ],
    )
    assert len(result["matches"]) == 1
    assert result["matches"][0]["prediction_index"] == 1
    assert result["false_positives"] == [0]


def test_segment_confusion_tracks_uncertain_as_its_own_class():
    scores = classification_scores(
        ["blocked", "clear"], ["uncertain", "blocked"], ["blocked", "partial", "clear", "uncertain"]
    )
    assert scores["confusion_matrix"]["blocked"]["uncertain"] == 1
    assert scores["confusion_matrix"]["clear"]["blocked"] == 1


def test_oracle_scores_all_supported_tasks_perfectly():
    scene = {
        "scene_id": "S-0001",
        "difficulty": "easy",
        "truth": {
            "hazards": [{"type": "flood", "bbox": [0, 0, 10, 10]}],
            "segments": {"A": "blocked", "B": "clear", "C": "partial"},
            "damaged_building_count": 1,
            "water_regions": [{"bbox": [2, 2, 5, 5]}],
            "routes": {"A-B": "obstructed", "B-C": "clear"},
            "zone_comparisons": {"north-south": "north"},
        },
        "prediction": {
            "hazards": [{"type": "flood", "bbox": [0, 0, 10, 10], "confidence": 1}],
            "segments": {"A": "blocked", "B": "clear", "C": "partial"},
            "segment_details": {
                "A": {"blocked_confidence": 1},
                "B": {"blocked_confidence": 0},
                "C": {"blocked_confidence": 0},
            },
            "damaged_building_count": 1,
            "water_regions": [{"bbox": [2, 2, 5, 5]}],
            "routes": {"A-B": "obstructed", "B-C": "clear"},
            "zone_comparisons": {"north-south": "north"},
        },
    }
    result = evaluate([scene])
    assert result.metrics["detection"].metrics["f1"] == 1
    assert result.metrics["detection"].metrics["macro_f1"] == 1
    assert result.metrics["segments"].metrics["accuracy"] == 1
    assert result.metrics["segments"].metrics["macro_f1"] == 1
    assert result.metrics["counts"].metrics["exact_match"] == 1
    assert result.metrics["water"].metrics["f1"] == 1
    assert result.metrics["water"].metrics["mean_iou"] == 1
    assert result.metrics["routes"].metrics["accuracy"] == 1
    assert result.metrics["zones"].metrics["accuracy"] == 1
    assert result.metrics["calibration"].metrics["brier_score"] == 0
    assert result.metrics["reliability"].metrics["valid_json_rate"] == 1
    assert result.metrics["routes"].details["obstructed"]["f1"] == 1
    assert result.route_impact["unsafe_route_rate"] == 0
    assert result.failures == []


def test_always_clear_false_clear_rate_equals_blocked_share():
    scenes = [
        {
            "truth": {"segments": {"a": "blocked", "b": "clear", "c": "blocked", "d": "partial"}},
            "prediction": {"segments": {"a": "clear", "b": "clear", "c": "clear", "d": "clear"}},
        }
    ]
    result = evaluate(scenes)
    assert result.metrics["segments"].metrics["false_clear_rate"] == 0.5
    assert result.metrics["segments"].metrics["blocked_miss_rate"] == 1


def test_route_impact_flags_path_through_true_blocked_segment():
    scene = {
        "difficulty": "easy",
        "road_graph": {
            "routes": [{"origin": "A", "destination": "C"}],
            "segments": [
                {"id": "AB", "from": "A", "to": "B", "length": 1},
                {"id": "BC", "from": "B", "to": "C", "length": 1},
                {"id": "AC", "from": "A", "to": "C", "length": 10},
            ],
        },
        "truth": {"segments": {"AB": "blocked", "BC": "clear", "AC": "clear"}},
        "prediction": {"segments": {"AB": "clear", "BC": "clear", "AC": "clear"}},
    }
    assert score_route_impact([scene])["unsafe_route_rate"] == 1


def test_calibration_bins_include_empty_bins():
    result = score_calibration(
        [
            {
                "truth": {"segments": {"a": "blocked"}},
                "prediction": {"segment_details": {"a": {"blocked_confidence": 0.8}}},
            }
        ]
    )
    assert len(result["bins"]) == 5
    assert result["brier_score"] == pytest.approx(0.04)


def test_contract_rejects_confidence_above_safety_cap():
    with pytest.raises(ValidationError):
        SegmentVerdict(status="clear", confidence=0.86)


def test_box_contract_uses_ordered_pixel_coordinate_array():
    assert Box.model_validate([1, 2, 3, 4]).model_dump() == (1.0, 2.0, 3.0, 4.0)
    with pytest.raises(ValidationError):
        Box.model_validate([3, 1, 2, 4])


def test_split_selection_prevents_dev_and_test_mixing():
    scenes = [{"scene_id": "S-DEV", "split": "dev"}, {"scene_id": "S-TEST", "split": "test"}]
    assert [scene["scene_id"] for scene in select_split(scenes, "test")] == ["S-TEST"]
    with pytest.raises(ValueError, match="declare its split"):
        select_split([{"scene_id": "S-UNKNOWN"}], "dev")


def test_input_join_marks_missing_prediction_invalid_and_preserves_scene(tmp_path):
    dataset = tmp_path / "dataset.json"
    predictions = tmp_path / "predictions.json"
    dataset.write_text(
        '{"scenes":[{"scene_id":"S-1","split":"dev","truth":{"segments":{"A":"blocked"}}}]}'
    )
    predictions.write_text('{"model_id":"sample","is_mock":true,"scenes":[]}')
    scene = load_scenes(dataset, predictions)[0]
    assert scene["scene_id"] == "S-1"
    assert scene["prediction"]["valid_json"] is False


def test_missing_prediction_is_counted_as_invalid_output():
    result = evaluate(
        [
            {
                "scene_id": "S-1",
                "difficulty": "easy",
                "truth": {"segments": {"A": "blocked"}},
                "prediction": {"valid_json": False, "raw_output": None},
            }
        ]
    )
    assert result.metrics["reliability"].metrics["valid_json_rate"] == 0
    assert any(failure.category == "invalid_output" for failure in result.failures)


def test_failures_distinguish_near_miss_from_other_false_blocks():
    result = evaluate(
        [
            {
                "scene_id": "S-1",
                "truth": {"segments": {"A": "clear", "B": "clear"}},
                "near_miss_segments": ["A"],
                "prediction": {"segments": {"A": "blocked", "B": "blocked"}},
            }
        ]
    )
    categories = {failure.question: failure.category for failure in result.failures}
    assert categories == {"A": "near_miss_false_block", "B": "false_block"}


def test_route_failures_tag_false_clear_answers_as_near_misses_only_when_marked():
    result = evaluate(
        [
            {
                "scene_id": "S-1",
                "near_miss_questions": ["A-B"],
                "truth": {"segments": {}, "routes": {"A-B": "clear", "A-C": "clear"}},
                "prediction": {
                    "segments": {},
                    "routes": {"A-B": "obstructed", "A-C": "obstructed"},
                },
            }
        ]
    )
    categories = {failure.question: failure.category for failure in result.failures}
    assert categories == {"A-B": "near_miss_false_block", "A-C": "false_block"}


def test_prediction_metadata_is_read_for_run_attribution(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text('{"model_id":"adapter-1","prompt_version":"p3","is_mock":true}')
    metadata = load_prediction_metadata(path)
    assert metadata["model_id"] == "adapter-1"
    assert metadata["prompt_version"] == "p3"
    assert metadata["is_mock"] is True


def test_prediction_metadata_is_inferred_and_mixed_runs_are_rejected(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text(
        '{"scenes":[{"scene_id":"S-1","model_id":"model-a","prompt_version":"p1",'
        '"is_mock":true,"prediction":{}},{"scene_id":"S-2","model_id":"model-b",'
        '"prompt_version":"p1","is_mock":true,"prediction":{}}]}'
    )
    with pytest.raises(ValueError, match="mix multiple model_id"):
        load_prediction_metadata(path)
    path.write_text(
        '{"scenes":[{"scene_id":"S-1","model_id":"model-a","prompt_version":"p1",'
        '"is_mock":true,"prediction":{}}]}'
    )
    metadata = load_prediction_metadata(path)
    assert metadata["model_id"] == "model-a"
    assert metadata["is_mock"] is True


def test_input_join_rejects_duplicate_and_unknown_prediction_ids(tmp_path):
    dataset = tmp_path / "dataset.json"
    predictions = tmp_path / "predictions.json"
    dataset.write_text('{"scenes":[{"scene_id":"S-1","split":"dev","truth":{}}]}')
    predictions.write_text(
        '{"scenes":[{"scene_id":"S-9","prediction":{}},{"scene_id":"S-9","prediction":{}}]}'
    )
    with pytest.raises(ValueError, match="Duplicate scene IDs"):
        load_scenes(dataset, predictions)
    predictions.write_text('{"scenes":[{"scene_id":"S-9","prediction":{}}]}')
    with pytest.raises(ValueError, match="unknown scene IDs"):
        load_scenes(dataset, predictions)


def test_invalid_prediction_shape_is_recorded_instead_of_crashing(tmp_path):
    dataset = tmp_path / "dataset.json"
    predictions = tmp_path / "predictions.json"
    dataset.write_text('{"scenes":[{"scene_id":"S-1","split":"dev","truth":{"segments":{}}}]}')
    predictions.write_text('{"scenes":[{"scene_id":"S-1","prediction":{"segments":[]}}]}')
    scene = load_scenes(dataset, predictions)[0]
    assert scene["prediction"]["valid_json"] is False
    assert "segments must be a mapping" in scene["prediction"]["validation_errors"]


def test_shared_scene_analysis_contract_maps_to_evaluator_fields(tmp_path):
    dataset = tmp_path / "dataset.json"
    predictions = tmp_path / "predictions.json"
    dataset.write_text(
        '{"scenes":[{"scene_id":"S-1","split":"dev",'
        '"ground_truth":{"segment_status":{"SEG-1":"blocked"}}}]}'
    )
    predictions.write_text(
        '{"scenes":[{"scene_id":"S-1","segment_verdicts":{'
        '"SEG-1":{"status":"blocked","confidence":0.8}}}]}'
    )
    scene = load_scenes(dataset, predictions)[0]
    assert scene["truth"]["segments"] == {"SEG-1": "blocked"}
    assert scene["prediction"]["segments"] == {"SEG-1": "blocked"}
    assert scene["prediction"]["segment_details"]["SEG-1"]["blocked_confidence"] == 0.8

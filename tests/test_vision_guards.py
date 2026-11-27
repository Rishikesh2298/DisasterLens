"""
Unit tests for DisasterLens vision guards (dl.vision.guards).

Tests cover all required roadmap rules:
1. CLEAR with no hazard list becomes UNCERTAIN.
2. CLEAR with poor image quality becomes UNCERTAIN.
3. CLEAR with incomplete segment visibility becomes UNCERTAIN.
4. CLEAR with mapper overlap >= 30% becomes UNCERTAIN.
5. BLOCKED with mapper CLEAR becomes UNCERTAIN.
6. CLEAR confidence never exceeds 0.85.
7. A verdict changed by a guard has an explanation identifying the responsible guard.
8. A valid verdict that violates none of the guard rules remains unchanged.
Additionally tests Rule 5 (safe verdict rejected) and edge cases.
"""

from __future__ import annotations

import pytest

from dl.contracts.enums import HazardType, RoadStatus
from dl.contracts.scene import Box
from dl.contracts.vision import PredictedHazard, SceneAnalysis, SegmentVerdict
from dl.vision.guards import (
    GuardChange,
    apply_guards,
    guard_segment_verdict,
)
from dl.vision.mapper import RoadMappingResult


def _make_sample_hazard() -> PredictedHazard:
    return PredictedHazard(
        type=HazardType.DEBRIS,
        bbox=Box((10.0, 10.0, 50.0, 50.0)),
        confidence=0.9,
    )


def _make_valid_clear_analysis(
    scene_id: str = "S-0001",
    segment_id: str = "SEG-001",
    confidence: float = 0.80,
    evidence: str = "No obstruction detected.",
    visible: bool = True,
    image_quality_good: bool = True,
    with_hazards: bool = True,
) -> SceneAnalysis:
    """Helper to create a fully valid CLEAR SceneAnalysis that passes all rules."""
    hazards = [_make_sample_hazard()] if with_hazards else []
    return SceneAnalysis(
        scene_id=scene_id,
        hazards=hazards,
        segment_verdicts={
            segment_id: SegmentVerdict(
                status=RoadStatus.CLEAR,
                confidence=confidence,
                evidence=evidence,
                visible=visible,
            )
        },
        damaged_building_count=0,
        water_regions=[],
        image_quality_good=image_quality_good,
        model_id="test-model",
        prompt_version="v1",
        valid_json=True,
        latency_ms=50,
    )


# =============================================================================
# 1. Test Rule 1: Missing Hazard List
# =============================================================================

class TestRule1MissingHazardList:
    """Test Rule 1: A CLEAR verdict requires the model to produce a hazard list."""

    def test_clear_with_no_hazard_list_becomes_uncertain_via_flag(self):
        analysis = _make_valid_clear_analysis()
        guarded, changes = apply_guards(analysis, has_hazard_list=False, return_changes=True)

        verdict = guarded.segment_verdicts["SEG-001"]
        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in verdict.evidence
        assert "hazard list" in verdict.evidence

        assert len(changes) == 1
        assert "Rule 1" in changes[0].guard_name
        assert changes[0].new_status == RoadStatus.UNCERTAIN

    def test_clear_with_no_hazard_list_omitted_field(self):
        # Construct analysis where hazards field was omitted (not in model_fields_set)
        analysis = SceneAnalysis(
            scene_id="S-0001",
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.CLEAR,
                    confidence=0.80,
                    evidence="Looks clear",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        guarded = apply_guards(analysis)
        verdict = guarded.segment_verdicts["SEG-001"]
        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in verdict.evidence

    def test_clear_with_none_hazard_list(self):
        analysis = _make_valid_clear_analysis()
        analysis.hazards = None  # type: ignore[assignment]
        guarded = apply_guards(analysis)
        verdict = guarded.segment_verdicts["SEG-001"]
        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in verdict.evidence


# =============================================================================
# 2. Test Rule 1: Poor Image Quality
# =============================================================================

class TestRule1PoorImageQuality:
    """Test Rule 1: A CLEAR verdict requires good image quality."""

    def test_clear_with_poor_image_quality_becomes_uncertain(self):
        analysis = _make_valid_clear_analysis(image_quality_good=False)
        guarded, changes = apply_guards(analysis, return_changes=True)

        verdict = guarded.segment_verdicts["SEG-001"]
        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in verdict.evidence
        assert "image quality" in verdict.evidence

        assert len(changes) == 1
        assert changes[0].new_status == RoadStatus.UNCERTAIN
        assert "image quality" in changes[0].guard_name.lower()

    def test_clear_with_none_image_quality_becomes_uncertain(self):
        analysis = _make_valid_clear_analysis()
        analysis.image_quality_good = None
        guarded = apply_guards(analysis)

        verdict = guarded.segment_verdicts["SEG-001"]
        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in verdict.evidence

    def test_clear_with_image_quality_override(self):
        analysis = _make_valid_clear_analysis(image_quality_good=True)
        # Explicit override to False
        guarded = apply_guards(analysis, image_quality_good=False)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.UNCERTAIN


# =============================================================================
# 3. Test Rule 1: Incomplete Segment Visibility
# =============================================================================

class TestRule1IncompleteVisibility:
    """Test Rule 1: A CLEAR verdict requires full segment visibility."""

    def test_clear_with_visible_false_becomes_uncertain(self):
        analysis = _make_valid_clear_analysis(visible=False)
        guarded, changes = apply_guards(analysis, return_changes=True)

        verdict = guarded.segment_verdicts["SEG-001"]
        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in verdict.evidence
        assert "visibility" in verdict.evidence

        assert len(changes) == 1
        assert changes[0].new_status == RoadStatus.UNCERTAIN
        assert "visibility" in changes[0].guard_name.lower()

    def test_clear_with_visible_none_becomes_uncertain(self):
        analysis = _make_valid_clear_analysis()
        analysis.segment_verdicts["SEG-001"].visible = None
        guarded = apply_guards(analysis)

        verdict = guarded.segment_verdicts["SEG-001"]
        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in verdict.evidence
        assert "visibility" in verdict.evidence

    def test_clear_with_visible_string_partial_becomes_uncertain(self):
        verdict = SegmentVerdict(status=RoadStatus.CLEAR, confidence=0.8, visible=True)
        # Assign string 'partial' post-init to test unvalidated model output
        verdict.visible = "partial"  # type: ignore[assignment]
        guarded, changes = guard_segment_verdict(verdict, "SEG-001", image_quality_good=True, has_hazard_list=True)

        assert guarded.status == RoadStatus.UNCERTAIN
        assert "Rule 1" in guarded.evidence


# =============================================================================
# 4. Test Rule 2: Mapper Overlap >= 30%
# =============================================================================

class TestRule2MapperOverlap:
    """Test Rule 2: Model CLEAR + mapper overlap >= 30% -> UNCERTAIN."""

    def test_clear_with_mapper_overlap_30_percent_becomes_uncertain(self):
        analysis = _make_valid_clear_analysis()
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.PARTIAL, max_coverage=0.30)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        verdict = guarded.segment_verdicts["SEG-001"]

        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 2" in verdict.evidence
        assert "mapper" in verdict.evidence.lower()

        assert len(changes) == 1
        assert "Rule 2" in changes[0].guard_name
        assert changes[0].new_status == RoadStatus.UNCERTAIN

    def test_clear_with_mapper_overlap_50_percent_becomes_uncertain(self):
        analysis = _make_valid_clear_analysis()
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.PARTIAL, max_coverage=0.50)}

        guarded = apply_guards(analysis, mapped_verdicts=mapped)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.UNCERTAIN
        assert "Rule 2" in guarded.segment_verdicts["SEG-001"].evidence

    def test_clear_with_mapper_overlap_blocked_becomes_uncertain(self):
        analysis = _make_valid_clear_analysis()
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.BLOCKED, max_coverage=0.95)}

        guarded = apply_guards(analysis, mapped_verdicts=mapped)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.UNCERTAIN
        assert "Rule 2" in guarded.segment_verdicts["SEG-001"].evidence

    def test_clear_with_mapper_dict_format(self):
        analysis = _make_valid_clear_analysis()
        mapped = {"SEG-001": {"status": "partial", "max_coverage": 0.40}}

        guarded = apply_guards(analysis, mapped_verdicts=mapped)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.UNCERTAIN
        assert "Rule 2" in guarded.segment_verdicts["SEG-001"].evidence

    def test_clear_with_mapper_overlap_below_30_percent_stays_clear(self):
        analysis = _make_valid_clear_analysis()
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.20)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.CLEAR
        assert len(changes) == 0


# =============================================================================
# 5. Test Rule 3: Model BLOCKED + Mapper CLEAR
# =============================================================================

class TestRule3MapperClearConflict:
    """Test Rule 3: Model BLOCKED + mapper CLEAR -> UNCERTAIN."""

    def test_blocked_with_mapper_clear_becomes_uncertain(self):
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.BLOCKED,
                    confidence=0.85,
                    evidence="Heavy obstruction visible",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.0)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        verdict = guarded.segment_verdicts["SEG-001"]

        assert verdict.status == RoadStatus.UNCERTAIN
        assert "Rule 3" in verdict.evidence
        assert "BLOCKED" in verdict.evidence
        assert "CLEAR" in verdict.evidence

        assert len(changes) == 1
        assert "Rule 3" in changes[0].guard_name
        assert changes[0].new_status == RoadStatus.UNCERTAIN

    def test_blocked_with_mapper_low_coverage_becomes_uncertain(self):
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.BLOCKED,
                    confidence=0.80,
                    evidence="Blockage reported",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        # Mapper coverage 10% is classified as CLEAR
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.10)}

        guarded = apply_guards(analysis, mapped_verdicts=mapped)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.UNCERTAIN
        assert "Rule 3" in guarded.segment_verdicts["SEG-001"].evidence

    def test_blocked_with_mapper_blocked_stays_blocked(self):
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.BLOCKED,
                    confidence=0.85,
                    evidence="Road blocked",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.BLOCKED, max_coverage=0.95)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.BLOCKED
        assert len(changes) == 0

    def test_blocked_with_mapper_partial_stays_blocked(self):
        # Rule 3 triggers only when mapper says CLEAR; if mapper says PARTIAL, both agree road is affected
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.BLOCKED,
                    confidence=0.85,
                    evidence="Road blocked",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.PARTIAL, max_coverage=0.50)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.BLOCKED
        assert len(changes) == 0


# =============================================================================
# 6. Test Rule 4: Confidence Cap (0.85)
# =============================================================================

class TestRule4ConfidenceCap:
    """Test Rule 4: Cap confidence of a no-obstruction/CLEAR verdict at 0.85."""

    def test_clear_confidence_at_or_below_limit_unchanged(self):
        analysis = _make_valid_clear_analysis(confidence=0.85)
        guarded, changes = apply_guards(analysis, return_changes=True)
        assert guarded.segment_verdicts["SEG-001"].confidence == 0.85
        assert len(changes) == 0

        analysis_lower = _make_valid_clear_analysis(confidence=0.70)
        guarded_lower = apply_guards(analysis_lower)
        assert guarded_lower.segment_verdicts["SEG-001"].confidence == 0.70

    def test_clear_confidence_above_limit_is_capped(self):
        verdict = SegmentVerdict(status=RoadStatus.CLEAR, confidence=0.85, visible=True)
        verdict.confidence = 0.95  # Post-init unvalidated assignment
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={"SEG-001": verdict},
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        guarded, changes = apply_guards(analysis, return_changes=True)
        guarded_verdict = guarded.segment_verdicts["SEG-001"]

        assert guarded_verdict.confidence <= 0.85
        assert guarded_verdict.confidence == 0.85
        assert any("Rule 4" in c.guard_name for c in changes)

    def test_standalone_guard_segment_verdict_caps_confidence(self):
        verdict = SegmentVerdict(status=RoadStatus.CLEAR, confidence=0.85, visible=True)
        verdict.confidence = 1.0  # Post-init assignment
        guarded_v, changes = guard_segment_verdict(verdict, "SEG-001", image_quality_good=True, has_hazard_list=True)

        assert guarded_v.confidence <= 0.85
        assert guarded_v.confidence == 0.85
        assert any("Rule 4" in c.guard_name for c in changes)


# =============================================================================
# 7. Test Rule 5: Forbidden Safe Verdict
# =============================================================================

class TestRule5ForbiddenSafeVerdict:
    """Test Rule 5: Never produce a SAFE verdict; change to UNCERTAIN."""

    def test_safe_status_becomes_uncertain(self):
        verdict = SegmentVerdict(status=RoadStatus.CLEAR, confidence=0.80, visible=True)
        verdict.status = "safe"  # type: ignore[assignment]
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={"SEG-001": verdict},
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        guarded, changes = apply_guards(analysis, return_changes=True)
        guarded_v = guarded.segment_verdicts["SEG-001"]

        assert guarded_v.status == RoadStatus.UNCERTAIN
        assert "Rule 5" in guarded_v.evidence
        assert "safe" in guarded_v.evidence.lower()
        assert any("Rule 5" in c.guard_name for c in changes)


# =============================================================================
# 8. Test Rule 6: Guard Explanation Tracking
# =============================================================================

class TestRule6ExplanationTracking:
    """Test Rule 6: A verdict changed by a guard has an explanation identifying the responsible guard."""

    def test_explanation_identifies_rule1(self):
        analysis = _make_valid_clear_analysis(image_quality_good=False)
        guarded = apply_guards(analysis)
        evidence = guarded.segment_verdicts["SEG-001"].evidence
        assert "Guard Rule 1" in evidence
        assert "image quality" in evidence

    def test_explanation_identifies_rule2(self):
        analysis = _make_valid_clear_analysis()
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.PARTIAL, max_coverage=0.45)}
        guarded = apply_guards(analysis, mapped_verdicts=mapped)
        evidence = guarded.segment_verdicts["SEG-001"].evidence
        assert "Guard Rule 2" in evidence
        assert "overlap" in evidence

    def test_explanation_identifies_rule3(self):
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.BLOCKED,
                    confidence=0.80,
                    evidence="Blockage",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.0)}
        guarded = apply_guards(analysis, mapped_verdicts=mapped)
        evidence = guarded.segment_verdicts["SEG-001"].evidence
        assert "Guard Rule 3" in evidence

    def test_prior_evidence_preserved(self):
        analysis = _make_valid_clear_analysis(evidence="Initial model assessment.")
        analysis.image_quality_good = False
        guarded = apply_guards(analysis)
        evidence = guarded.segment_verdicts["SEG-001"].evidence
        assert "Guard Rule 1" in evidence
        assert "Initial model assessment." in evidence


# =============================================================================
# 9. Test Valid Verdicts Remain Unchanged
# =============================================================================

class TestValidVerdictsUnchanged:
    """Test 8: A valid verdict that violates none of the guard rules remains unchanged."""

    def test_valid_clear_verdict_remains_unchanged(self):
        analysis = _make_valid_clear_analysis(confidence=0.80, evidence="Clean pavement.")
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.05)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        v = guarded.segment_verdicts["SEG-001"]

        assert v.status == RoadStatus.CLEAR
        assert v.confidence == 0.80
        assert v.evidence == "Clean pavement."
        assert v.visible is True
        assert len(changes) == 0

    def test_valid_blocked_verdict_remains_unchanged(self):
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.BLOCKED,
                    confidence=0.85,
                    evidence="Road completely blocked by flood waters.",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.BLOCKED, max_coverage=0.95)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        v = guarded.segment_verdicts["SEG-001"]

        assert v.status == RoadStatus.BLOCKED
        assert v.confidence == 0.85
        assert v.evidence == "Road completely blocked by flood waters."
        assert len(changes) == 0

    def test_valid_partial_verdict_remains_unchanged(self):
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                "SEG-001": SegmentVerdict(
                    status=RoadStatus.PARTIAL,
                    confidence=0.75,
                    evidence="Single lane obstructed.",
                    visible=True,
                )
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        mapped = {"SEG-001": RoadMappingResult(status=RoadStatus.PARTIAL, max_coverage=0.55)}

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)
        v = guarded.segment_verdicts["SEG-001"]

        assert v.status == RoadStatus.PARTIAL
        assert v.confidence == 0.75
        assert v.evidence == "Single lane obstructed."
        assert len(changes) == 0


# =============================================================================
# 10. Multi-segment & Integration Tests
# =============================================================================

class TestMultiSegmentGuards:
    """Test multi-segment interactions and independence."""

    def test_multi_segment_independent_guards(self):
        analysis = SceneAnalysis(
            scene_id="S-0001",
            hazards=[_make_sample_hazard()],
            segment_verdicts={
                # Seg 1: Valid CLEAR
                "SEG-001": SegmentVerdict(status=RoadStatus.CLEAR, confidence=0.80, visible=True),
                # Seg 2: CLEAR with incomplete visibility -> UNCERTAIN
                "SEG-002": SegmentVerdict(status=RoadStatus.CLEAR, confidence=0.80, visible=False),
                # Seg 3: BLOCKED with mapper CLEAR -> UNCERTAIN
                "SEG-003": SegmentVerdict(status=RoadStatus.BLOCKED, confidence=0.85, visible=True),
                # Seg 4: BLOCKED with mapper BLOCKED -> stays BLOCKED
                "SEG-004": SegmentVerdict(status=RoadStatus.BLOCKED, confidence=0.85, visible=True),
            },
            image_quality_good=True,
            model_id="test-model",
            prompt_version="v1",
        )
        mapped = {
            "SEG-001": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.0),
            "SEG-002": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.0),
            "SEG-003": RoadMappingResult(status=RoadStatus.CLEAR, max_coverage=0.0),
            "SEG-004": RoadMappingResult(status=RoadStatus.BLOCKED, max_coverage=1.0),
        }

        guarded, changes = apply_guards(analysis, mapped_verdicts=mapped, return_changes=True)

        assert guarded.segment_verdicts["SEG-001"].status == RoadStatus.CLEAR
        assert guarded.segment_verdicts["SEG-002"].status == RoadStatus.UNCERTAIN
        assert guarded.segment_verdicts["SEG-003"].status == RoadStatus.UNCERTAIN
        assert guarded.segment_verdicts["SEG-004"].status == RoadStatus.BLOCKED

        changed_segs = {c.segment_id for c in changes}
        assert changed_segs == {"SEG-002", "SEG-003"}

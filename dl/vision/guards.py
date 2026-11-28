"""
Guard rules for DisasterLens Vision AI engine.

Enforces safety and consistency checks on model predictions and mapper outputs:
- Rule 1: A CLEAR verdict is only allowed if the model produced a hazard list,
          the image quality is good, and the segment is fully visible.
          Otherwise, change the verdict to UNCERTAIN.
- Rule 2: If the model says CLEAR but the mapper finds hazard overlap of 30% or more,
          change the verdict to UNCERTAIN.
- Rule 3: If the model says BLOCKED but the mapper says CLEAR,
          change the verdict to UNCERTAIN.
- Rule 4: Cap the confidence of a no-obstruction/CLEAR verdict at 0.85.
- Rule 5: Never produce a SAFE verdict; the contract does not have a SAFE value.
          Any 'safe' verdict is changed to UNCERTAIN.
- Rule 6: Record which guard changed the verdict so that the change can be explained.
          Explanations are recorded in the existing 'evidence' field of SegmentVerdict.

Contract Limitations & Safety Constraints:
- SegmentVerdict.confidence is capped at 0.85 per the shared schema.
- The shared contract (dl/contracts/vision.py) does not have a structured reason field,
  is_mock, or is_baseline field (extra="forbid" is enforced). Guard explanations
  are recorded exclusively in the existing 'evidence' string field.
- Visibility in the contract is boolean (visible: bool | None). Full visibility is
  represented by `visible is True`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dl.contracts.enums import RoadStatus
from dl.contracts.vision import SceneAnalysis, SegmentVerdict
from dl.vision.mapper import RoadMappingResult

# Constants
MAX_CLEAR_CONFIDENCE: float = 0.85
MAPPER_OVERLAP_THRESHOLD: float = 0.30


@dataclass(frozen=True)
class GuardChange:
    """Record of a change made to a segment verdict by a guard rule."""

    segment_id: str
    guard_name: str
    original_status: str
    new_status: RoadStatus
    original_confidence: float
    new_confidence: float
    reason: str


def _check_hazard_list_produced(
    analysis: SceneAnalysis | dict[str, Any],
    has_hazard_list: bool | None = None,
) -> bool:
    """
    Determine whether the model produced a hazard list.

    Returns False if:
    - has_hazard_list is explicitly False
    - analysis.hazards is None
    - 'hazards' was omitted from the model output / fields_set
    """
    if has_hazard_list is not None:
        return bool(has_hazard_list)

    if isinstance(analysis, dict):
        return "hazards" in analysis and analysis["hazards"] is not None

    # Pydantic SceneAnalysis instance
    if getattr(analysis, "hazards", None) is None:
        return False

    return not (
        hasattr(analysis, "model_fields_set")
        and "hazards" not in analysis.model_fields_set
    )


def _extract_mapper_info(
    mapped_item: RoadMappingResult | RoadStatus | float | dict[str, Any] | None,
) -> tuple[RoadStatus | None, float | None]:
    """
    Extract (status, max_coverage) from various representations of a mapper result.
    """
    if mapped_item is None:
        return None, None

    if isinstance(mapped_item, RoadMappingResult):
        return mapped_item.status, mapped_item.max_coverage

    if isinstance(mapped_item, RoadStatus):
        return mapped_item, None

    if isinstance(mapped_item, (int, float)):
        cov = float(mapped_item)
        if cov >= 0.90:
            status = RoadStatus.BLOCKED
        elif cov >= MAPPER_OVERLAP_THRESHOLD:
            status = RoadStatus.PARTIAL
        else:
            status = RoadStatus.CLEAR
        return status, cov

    if isinstance(mapped_item, dict):
        raw_status = mapped_item.get("status")
        parsed_status: RoadStatus | None = None
        if isinstance(raw_status, RoadStatus):
            parsed_status = raw_status
        elif isinstance(raw_status, str):
            try:
                parsed_status = RoadStatus(raw_status.lower())
            except ValueError:
                parsed_status = None

        cov = mapped_item.get("max_coverage", mapped_item.get("coverage"))
        cov_float = float(cov) if cov is not None else None
        return parsed_status, cov_float

    return None, None


def _format_guard_evidence(
    guard_tag: str,
    reason: str,
    original_evidence: str,
) -> str:
    """Format updated evidence preserving any prior reasoning."""
    prefix = f"[{guard_tag}] {reason}"
    if original_evidence and original_evidence.strip():
        return f"{prefix} (Prior evidence: {original_evidence.strip()})"
    return prefix


def guard_segment_verdict(
    verdict: SegmentVerdict,
    segment_id: str = "",
    *,
    image_quality_good: bool | None = True,
    has_hazard_list: bool = True,
    mapped_result: RoadMappingResult | RoadStatus | float | dict[str, Any] | None = None,
) -> tuple[SegmentVerdict, list[GuardChange]]:
    """
    Apply guard rules to a single segment verdict.

    Args:
        verdict: Input SegmentVerdict to validate and guard.
        segment_id: Identifier of the road segment.
        image_quality_good: Boolean indicating if image quality is acceptable.
        has_hazard_list: Boolean indicating if model produced a hazard list.
        mapped_result: Geometric mapper output for this segment.

    Returns:
        tuple of (Guarded SegmentVerdict, list of GuardChange records).
    """
    changes: list[GuardChange] = []

    original_status_raw = getattr(verdict, "status", None)
    original_status_str = str(original_status_raw).lower() if original_status_raw else "unknown"
    current_status_str = original_status_str
    current_confidence = float(verdict.confidence)
    current_evidence = verdict.evidence
    current_visible = verdict.visible

    mapped_status, mapped_coverage = _extract_mapper_info(mapped_result)

    # -------------------------------------------------------------------------
    # Rule 5: Never produce a SAFE verdict. The contract does not have a SAFE value.
    # -------------------------------------------------------------------------
    if current_status_str == "safe":
        reason = "Guard Rule 5: 'safe' is not a permitted status in the DisasterLens contract; changed to UNCERTAIN."
        changes.append(
            GuardChange(
                segment_id=segment_id,
                guard_name="Guard Rule 5 (forbidden 'safe' verdict)",
                original_status=original_status_str,
                new_status=RoadStatus.UNCERTAIN,
                original_confidence=current_confidence,
                new_confidence=current_confidence,
                reason=reason,
            )
        )
        current_status_str = RoadStatus.UNCERTAIN.value
        current_evidence = _format_guard_evidence("Guard Rule 5: Forbidden Safe Verdict", reason, current_evidence)

    # -------------------------------------------------------------------------
    # Rule 1: A CLEAR verdict is allowed only when:
    #         - The model produced a hazard list.
    #         - Image quality is good.
    #         - The segment is fully visible.
    #         Otherwise, change the verdict to UNCERTAIN.
    # -------------------------------------------------------------------------
    if current_status_str == RoadStatus.CLEAR.value:
        rule1_failures: list[str] = []

        if not has_hazard_list:
            rule1_failures.append("model did not produce a hazard list")

        if image_quality_good is not True:
            rule1_failures.append(f"image quality is not good (image_quality_good={image_quality_good})")

        # Full visibility is represented by visible is True
        is_fully_visible = current_visible is True or (
            isinstance(current_visible, str) and str(current_visible).lower() == "full"
        )
        if not is_fully_visible:
            rule1_failures.append(f"segment visibility is incomplete (visible={current_visible})")

        if rule1_failures:
            reasons_joined = "; ".join(rule1_failures)
            reason = f"Guard Rule 1: Changed CLEAR to UNCERTAIN because {reasons_joined}."
            guard_name = f"Guard Rule 1 ({', '.join(rule1_failures)})"
            changes.append(
                GuardChange(
                    segment_id=segment_id,
                    guard_name=guard_name,
                    original_status=original_status_str,
                    new_status=RoadStatus.UNCERTAIN,
                    original_confidence=current_confidence,
                    new_confidence=current_confidence,
                    reason=reason,
                )
            )
            current_status_str = RoadStatus.UNCERTAIN.value
            current_evidence = _format_guard_evidence("Guard Rule 1: Unverified Clear", reason, current_evidence)

    # -------------------------------------------------------------------------
    # Rule 2: If the model says CLEAR but the mapper finds hazard overlap of 30% or more,
    #         change the verdict to UNCERTAIN.
    # -------------------------------------------------------------------------
    if current_status_str == RoadStatus.CLEAR.value:
        has_overlap_30 = False
        cov_desc = ""

        if mapped_coverage is not None:
            if mapped_coverage >= (MAPPER_OVERLAP_THRESHOLD - 1e-6):
                has_overlap_30 = True
                cov_desc = f"coverage={mapped_coverage:.1%}"
        elif mapped_status in (RoadStatus.PARTIAL, RoadStatus.BLOCKED):
            has_overlap_30 = True
            cov_desc = f"status={mapped_status.value}"

        if has_overlap_30:
            reason = (
                f"Guard Rule 2: Model predicted CLEAR but mapper detected hazard overlap >= 30% "
                f"({cov_desc}). Changed to UNCERTAIN."
            )
            changes.append(
                GuardChange(
                    segment_id=segment_id,
                    guard_name="Guard Rule 2 (mapper overlap conflict)",
                    original_status=original_status_str,
                    new_status=RoadStatus.UNCERTAIN,
                    original_confidence=current_confidence,
                    new_confidence=current_confidence,
                    reason=reason,
                )
            )
            current_status_str = RoadStatus.UNCERTAIN.value
            current_evidence = _format_guard_evidence("Guard Rule 2: Mapper Overlap Conflict", reason, current_evidence)

    # -------------------------------------------------------------------------
    # Rule 3: If the model says BLOCKED but the mapper says CLEAR,
    #         change the verdict to UNCERTAIN.
    # -------------------------------------------------------------------------
    if current_status_str == RoadStatus.BLOCKED.value:
        mapper_is_clear = False

        if mapped_status == RoadStatus.CLEAR or mapped_coverage is not None and mapped_coverage < MAPPER_OVERLAP_THRESHOLD:
            mapper_is_clear = True

        if mapper_is_clear:
            cov_info = f" (coverage={mapped_coverage:.1%})" if mapped_coverage is not None else ""
            reason = (
                f"Guard Rule 3: Model predicted BLOCKED but mapper detected CLEAR{cov_info}. "
                f"Changed to UNCERTAIN."
            )
            changes.append(
                GuardChange(
                    segment_id=segment_id,
                    guard_name="Guard Rule 3 (mapper clear conflict)",
                    original_status=original_status_str,
                    new_status=RoadStatus.UNCERTAIN,
                    original_confidence=current_confidence,
                    new_confidence=current_confidence,
                    reason=reason,
                )
            )
            current_status_str = RoadStatus.UNCERTAIN.value
            current_evidence = _format_guard_evidence("Guard Rule 3: Mapper Clear Conflict", reason, current_evidence)

    # -------------------------------------------------------------------------
    # Rule 4: Cap the confidence of a no-obstruction/CLEAR verdict at 0.85.
    #         (Also enforce 0.85 maximum ceiling for all verdicts per Pydantic contract).
    # -------------------------------------------------------------------------
    capped_confidence = max(0.0, min(current_confidence, MAX_CLEAR_CONFIDENCE))
    if current_confidence > MAX_CLEAR_CONFIDENCE:
        reason = f"Guard Rule 4: Capped confidence from {current_confidence:.2f} to {MAX_CLEAR_CONFIDENCE:.2f}."
        changes.append(
            GuardChange(
                segment_id=segment_id,
                guard_name="Guard Rule 4 (confidence cap)",
                original_status=current_status_str,
                new_status=RoadStatus(current_status_str),
                original_confidence=current_confidence,
                new_confidence=capped_confidence,
                reason=reason,
            )
        )
        current_confidence = capped_confidence
        current_evidence = _format_guard_evidence("Guard Rule 4: Confidence Cap", reason, current_evidence)

    # Reconstruct contract-valid RoadStatus enum
    final_status = RoadStatus(current_status_str)

    # Normalize visible to contract-valid bool | None
    normalized_visible: bool | None
    if isinstance(current_visible, bool) or current_visible is None:
        normalized_visible = current_visible
    elif isinstance(current_visible, str):
        val_lower = current_visible.strip().lower()
        if val_lower in ("true", "full", "1"):
            normalized_visible = True
        elif val_lower in ("false", "partial", "none", "0"):
            normalized_visible = False
        else:
            normalized_visible = None
    else:
        normalized_visible = bool(current_visible) if current_visible is not None else None

    # Build validated SegmentVerdict
    guarded_verdict = SegmentVerdict(
        status=final_status,
        confidence=capped_confidence,
        evidence=current_evidence,
        visible=normalized_visible,
    )

    return guarded_verdict, changes


def apply_guards(
    analysis: SceneAnalysis,
    mapped_verdicts: dict[str, Any] | None = None,
    *,
    has_hazard_list: bool | None = None,
    image_quality_good: bool | None = None,
    return_changes: bool = False,
) -> SceneAnalysis | tuple[SceneAnalysis, list[GuardChange]]:
    """
    Apply DisasterLens vision guard rules to an entire SceneAnalysis.

    Args:
        analysis: Validated SceneAnalysis contract object from vision adapter.
        mapped_verdicts: Optional mapping from segment_id to RoadMappingResult,
                         RoadStatus, coverage float, or dict.
        has_hazard_list: Explicit override for whether model produced hazard list.
                         If None, inferred from analysis.hazards and model_fields_set.
        image_quality_good: Explicit override for image quality. If None,
                            inferred from analysis.image_quality_good.
        return_changes: If True, returns a tuple of (guarded_analysis, list[GuardChange]).

    Returns:
        Guarded SceneAnalysis (and optionally list of GuardChange records).
    """
    effective_has_hazards = _check_hazard_list_produced(analysis, has_hazard_list=has_hazard_list)
    effective_img_quality = (
        image_quality_good if image_quality_good is not None else analysis.image_quality_good
    )

    all_changes: list[GuardChange] = []
    guarded_verdicts: dict[str, SegmentVerdict] = {}

    mapped_map = mapped_verdicts or {}

    for seg_id, verdict in analysis.segment_verdicts.items():
        mapped_result = mapped_map.get(seg_id)
        guarded_v, changes = guard_segment_verdict(
            verdict=verdict,
            segment_id=seg_id,
            image_quality_good=effective_img_quality,
            has_hazard_list=effective_has_hazards,
            mapped_result=mapped_result,
        )
        guarded_verdicts[seg_id] = guarded_v
        all_changes.extend(changes)

    # Construct clean guarded SceneAnalysis respecting Pydantic contract
    guarded_analysis = SceneAnalysis(
        scene_id=analysis.scene_id,
        hazards=list(analysis.hazards) if getattr(analysis, "hazards", None) is not None else [],
        segment_verdicts=guarded_verdicts,
        damaged_building_count=analysis.damaged_building_count,
        water_regions=list(analysis.water_regions) if getattr(analysis, "water_regions", None) is not None else [],
        image_quality_good=effective_img_quality,
        model_id=analysis.model_id,
        prompt_version=analysis.prompt_version,
        valid_json=analysis.valid_json,
        latency_ms=analysis.latency_ms,
    )

    if return_changes:
        return guarded_analysis, all_changes
    return guarded_analysis


# Functional aliases for compatibility
apply_guard_rules = apply_guards
guard_scene_analysis = apply_guards

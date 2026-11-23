"""
Segment router providing segment observation history.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query

from dl.api.dependencies import get_observation_service
from dl.api.services.observation_service import ObservationService

router = APIRouter(prefix="/segments", tags=["segments"])


@router.get("/{segment_id}/history")
def get_segment_history(
    segment_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    obs_service: ObservationService = Depends(get_observation_service),
) -> dict[str, Any]:
    """
    Returns full historical record of observations for a road segment.
    Strictly ordered by captured_at ascending. Uploaded_at is preserved for audit purposes.
    """
    records = obs_service.get_segment_history(segment_id, limit=limit, offset=offset)

    history_list: list[dict[str, Any]] = []
    for r in records:
        evidence = json.loads(r.evidence_json) if r.evidence_json else None
        history_list.append({
            "id": r.id,
            "observation_id": r.observation_id,
            "segment_id": r.segment_id,
            "source": r.source,
            "zone": r.zone,
            "verdict": r.verdict,
            "confidence": r.confidence,
            "max_coverage": r.max_coverage,
            "hazard_type": r.hazard_type,
            "near_miss": r.near_miss,
            "recovery": r.recovery,
            "visibility": r.visibility,
            "direct_verdict": r.direct_verdict,
            "mapped_verdict": r.mapped_verdict,
            "captured_at": r.captured_at.isoformat(),
            "uploaded_at": r.uploaded_at.isoformat(),
            "analyzed_at": r.analyzed_at.isoformat() if getattr(r, "analyzed_at", None) else None,
            "model_id": getattr(r, "model_id", None),
            "is_mock": getattr(r, "is_mock", True),
            "image_path": getattr(r, "image_path", None),
            "original_filename": getattr(r, "original_filename", None),
            "evidence": evidence,
        })

    return {
        "segment_id": segment_id,
        "count": len(history_list),
        "limit": limit,
        "offset": offset,
        "history": history_list,
    }

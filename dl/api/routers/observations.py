"""
Observation router supporting JSON payloads (ScenarioPlayer-compatible) and multipart image uploads.

Includes content-based image validation, secure unique naming, upload size guards,
path traversal prevention, input validation, and structured logging.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from dl.api.config import settings
from dl.api.dependencies import get_clock_service, get_observation_service, get_storage_service
from dl.api.services.clock_service import ClockService
from dl.api.services.observation_service import ObservationService
from dl.api.storage import ImageStorageService
from dl.contracts.observation import SegmentObservation
from dl.contracts.scene import HazardType, RoadStatus, Zone
from dl.routing.freshness import normalize_datetime
from dl.vision.provider import VisionProviderError, get_vision_provider

logger = logging.getLogger("dl.api.observations")

router = APIRouter(prefix="/observations", tags=["observations"])

# Supported zones and segment pattern
VALID_ZONES = {Zone.NW, Zone.NE, Zone.SW, Zone.SE}
VALID_ZONE_VALUES = {z.value for z in VALID_ZONES}
SEGMENT_ID_REGEX = re.compile(r"^SEG-\d{3}$")
VALID_VERDICTS = {"CLEAR", "BLOCKED", "PARTIAL", "UNCERTAIN"}

# Boundary limit for demo timeline (Nov 22 - 28, 2026)
HACKATHON_DEMO_END = datetime(2026, 11, 28, 23, 59, 59, tzinfo=UTC)


def validate_captured_at(
    val: Any,
    sim_time: datetime | None = None,
    as_of: datetime | None = None,
) -> datetime:
    """
    Validates that captured_at is present, is a valid ISO-8601 string,
    and is not in the future relative to the active evaluation time.
    """
    if not val:
        raise HTTPException(
            status_code=400,
            detail="Missing required capture timestamp ('captured_at' or 'capture_time').",
        )
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, str):
        cleaned = val.strip()
        try:
            dt = datetime.fromisoformat(cleaned)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid ISO 8601 timestamp format: '{val}'. Expected format e.g. '2026-11-27T08:00:00+05:30' or '2026-11-27T08:00:00Z'.",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Capture timestamp must be a valid ISO 8601 datetime string.",
        )

    norm_dt = normalize_datetime(dt)

    # Reference limit: explicit as_of -> active simulated time -> hackathon demo window / system time
    if as_of is not None:
        ref_limit = normalize_datetime(as_of)
    elif sim_time is not None:
        ref_limit = normalize_datetime(sim_time)
    else:
        ref_limit = max(datetime.now(UTC), HACKATHON_DEMO_END)

    if norm_dt > ref_limit + timedelta(seconds=60):
        raise HTTPException(
            status_code=400,
            detail=f"Observation capture timestamp {norm_dt.isoformat()} cannot be in the future relative to evaluation reference {ref_limit.isoformat()}.",
        )

    return norm_dt


def validate_zone(zone_val: Any) -> Zone:
    """Validates that zone is one of NW, NE, SW, SE."""
    if not zone_val:
        raise HTTPException(
            status_code=400,
            detail="Missing required 'zone' field. Must be one of NW, NE, SW, SE.",
        )
    val_str = str(zone_val).strip().upper()
    if val_str not in VALID_ZONE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid zone '{zone_val}'. Must be one of NW, NE, SW, SE.",
        )
    return Zone(val_str)


def validate_segment_id(seg_id: Any) -> str:
    """Validates that segment_id follows the canonical pattern (e.g. SEG-001)."""
    if not seg_id:
        raise HTTPException(status_code=400, detail="Missing required 'segment_id' field.")
    val_str = str(seg_id).strip().upper()
    if not SEGMENT_ID_REGEX.match(val_str):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid segment_id '{seg_id}'. Must follow pattern 'SEG-001'.",
        )
    return val_str


def validate_verdict(verdict_val: Any) -> RoadStatus:
    """Validates that verdict is a recognized road condition."""
    if not verdict_val:
        return RoadStatus.CLEAR
    val_str = str(verdict_val).strip().upper()
    if val_str not in VALID_VERDICTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid verdict '{verdict_val}'. Supported verdicts: {sorted(VALID_VERDICTS)}.",
        )
    return RoadStatus(val_str)


def validate_confidence(conf_val: Any) -> float:
    """Validates that confidence is a float between 0.0 and 1.0."""
    if conf_val is None:
        return 1.0
    try:
        val = float(conf_val)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid confidence value '{conf_val}'. Must be a float.")
    if not (0.0 <= val <= 1.0):
        raise HTTPException(
            status_code=400,
            detail=f"Confidence value {val} must be between 0.0 and 1.0.",
        )
    return val


def validate_max_coverage(cov_val: Any) -> float | None:
    """Validates that max_coverage is a float between 0.0 and 1.0 or None."""
    if cov_val is None:
        return None
    try:
        val = float(cov_val)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid max_coverage value '{cov_val}'. Must be a float.")
    if not (0.0 <= val <= 1.0):
        raise HTTPException(
            status_code=400,
            detail=f"Maximum coverage value {val} must be between 0.0 and 1.0.",
        )
    return val


class ObservationIngestResponse(BaseModel):
    """Structured response for observation ingestion."""

    observation_id: str
    affected_segments_count: int
    affected_segments: list[str]
    previous_statuses: dict[str, str]
    new_statuses: dict[str, str]
    alerts_count: int
    alerts: list[dict[str, Any]]
    image_path: str | None = None
    original_filename: str | None = None


@router.post("", response_model=ObservationIngestResponse)
async def ingest_observations(
    request: Request,
    as_of: datetime | None = Query(None, description="Optional evaluation timestamp for freshness boundary checks"),
    obs_service: ObservationService = Depends(get_observation_service),
    clock: ClockService = Depends(get_clock_service),
    storage: ImageStorageService = Depends(get_storage_service),
) -> ObservationIngestResponse:
    """
    Ingests observation payloads. Supports:
    1. Direct JSON (single object or list, ScenarioPlayer compatible with capture_time/captured_at)
    2. Multi-segment camera observations
    3. Multipart form uploads with image attachments and server-side storage
    """
    content_type = request.headers.get("content-type", "")
    sim_time = clock.get_simulated_time()

    raw_observations: list[dict[str, Any]] = []
    saved_image_path: str | None = None
    original_filename: str | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        image_file: UploadFile | None = form.get("image")  # type: ignore[assignment]

        # 1. Image upload processing and validation
        if image_file and hasattr(image_file, "filename") and image_file.filename:
            storage_ref, orig_name, byte_size = await storage.validate_and_save(image_file)
            saved_image_path = storage_ref
            original_filename = orig_name
            logger.info(
                "Uploaded image validated and stored: original=%s, ref=%s, bytes=%d",
                original_filename,
                saved_image_path,
                byte_size,
            )

        # 2. Extract and validate form fields
        seg_id = form.get("segment_id")
        aff_segs_raw = form.get("affected_segments")
        affected_segments: list[str] = []
        if aff_segs_raw:
            affected_segments = [validate_segment_id(s.strip()) for s in str(aff_segs_raw).split(",") if s.strip()]
        elif seg_id:
            affected_segments = [validate_segment_id(seg_id)]
        else:
            if saved_image_path:
                storage.delete_file(saved_image_path)
            raise HTTPException(status_code=400, detail="Missing required 'segment_id' or 'affected_segments'.")

        cap_time_raw = form.get("capture_time") or form.get("captured_at")
        try:
            norm_cap_time = validate_captured_at(cap_time_raw, sim_time=sim_time, as_of=as_of)
            validated_zone = validate_zone(form.get("zone"))
            validated_verdict = validate_verdict(form.get("verdict"))
            validated_conf = validate_confidence(form.get("confidence"))
            validated_cov = validate_max_coverage(form.get("max_coverage"))
        except HTTPException:
            if saved_image_path:
                storage.delete_file(saved_image_path)
            raise

        source = str(form.get("source") or "camera_upload").strip()
        hazard_str = form.get("hazard_type")
        hazard_enum = HazardType(hazard_str) if hazard_str and hazard_str in HazardType._value2member_map_ else None

        provider = get_vision_provider(settings.VISION_MODE, model=settings.VISION_MODEL)
        try:
            parsed = provider.process_observation_payload({
                "source": source,
                "zone": validated_zone.value,
                "affected_segments": affected_segments,
                "capture_time": norm_cap_time.isoformat(),
                "verdict": validated_verdict.value,
                "hazard_type": hazard_enum.value if hazard_enum else None,
                "confidence": validated_conf,
                "max_coverage": validated_cov,
                "image": original_filename,
            })
            for p in parsed:
                dumped = p.model_dump()
                dumped["image_path"] = saved_image_path
                dumped["original_filename"] = original_filename
                dumped["analyzed_at"] = datetime.now(UTC)
                raw_observations.append(dumped)
        except VisionProviderError as vpe:
            if saved_image_path:
                storage.delete_file(saved_image_path)
            raise HTTPException(status_code=501, detail=str(vpe))
        except Exception as e:
            if saved_image_path:
                storage.delete_file(saved_image_path)
            raise HTTPException(status_code=400, detail=f"Observation processing error: {e!s}")

    else:
        # JSON payload
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")

        provider = get_vision_provider(settings.VISION_MODE, model=settings.VISION_MODEL)

        if isinstance(body, list):
            items = body
        elif isinstance(body, dict) and "observations" in body and isinstance(body["observations"], list):
            items = body["observations"]
        elif isinstance(body, dict):
            items = [body]
        else:
            raise HTTPException(status_code=400, detail="Payload must be a JSON object or list.")

        for item in items:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="Observation item must be a JSON object.")

            cap_raw = item.get("capture_time") or item.get("captured_at")
            norm_cap = validate_captured_at(cap_raw, sim_time=sim_time, as_of=as_of)
            item["captured_at"] = norm_cap

            if "zone" in item:
                item["zone"] = validate_zone(item["zone"])
            if "confidence" in item:
                item["confidence"] = validate_confidence(item["confidence"])
            if "max_coverage" in item and item["max_coverage"] is not None:
                item["max_coverage"] = validate_max_coverage(item["max_coverage"])

            if item.get("affected_segments"):
                parsed_list = provider.process_observation_payload(item)
                for p in parsed_list:
                    dumped = p.model_dump()
                    dumped["analyzed_at"] = datetime.now(UTC)
                    raw_observations.append(dumped)
            else:
                if "segment_id" in item:
                    item["segment_id"] = validate_segment_id(item["segment_id"])
                item["analyzed_at"] = datetime.now(UTC)
                raw_observations.append(item)

    # Validate each observation into SegmentObservation model
    validated_list: list[SegmentObservation] = []
    for raw in raw_observations:
        try:
            if "capture_time" in raw and "captured_at" not in raw:
                raw["captured_at"] = raw["capture_time"]
            obs = SegmentObservation.model_validate(raw)
            validated_list.append(obs)
        except Exception as e:
            if saved_image_path:
                storage.delete_file(saved_image_path)
            raise HTTPException(status_code=422, detail=f"Invalid observation fields: {e!s}")

    if not validated_list:
        if saved_image_path:
            storage.delete_file(saved_image_path)
        raise HTTPException(status_code=400, detail="No valid observations found in payload.")

    # Ingest into observation service and fusion engine with transactional failure cleanup
    try:
        affected, alerts = obs_service.ingest_observations_bulk(validated_list, as_of=sim_time)
    except Exception as e:
        if saved_image_path:
            storage.delete_file(saved_image_path)
        logger.error("Failed to persist observation batch: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to persist observation: {e!s}")

    primary_id = validated_list[0].observation_id
    logger.info(
        "Observation ingestion complete: id=%s, affected_segments=%s, alerts=%d",
        primary_id,
        affected.affected_segment_ids,
        len(alerts.alerts),
    )

    return ObservationIngestResponse(
        observation_id=primary_id,
        affected_segments_count=len(affected.affected_segment_ids),
        affected_segments=affected.affected_segment_ids,
        previous_statuses={k: v.value for k, v in affected.previous_statuses.items()},
        new_statuses={k: v.value for k, v in affected.new_statuses.items()},
        alerts_count=len(alerts.alerts),
        alerts=[
            {
                "route_id": a.route_id,
                "alert_type": a.alert_type,
                "segment_id": a.segment_id,
                "message": a.message,
                "severity": a.severity,
            }
            for a in alerts.alerts
        ],
        image_path=saved_image_path,
        original_filename=original_filename,
    )

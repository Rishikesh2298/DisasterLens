"""
Deterministic mock vision provider for DisasterLens.

Produces reproducible SegmentObservation instances from synthetic scenes,
ground-truth records, or scenario timeline events.
Identified strictly as MOCK mode.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dl.contracts.observation import SegmentObservation
from dl.contracts.scene import GroundTruth, HazardType, RoadStatus, Scene, Zone


class MockVisionProvider:
    """
    Deterministic vision oracle and scenario converter.
    """

    MODEL_ID = "mock_oracle_v1"

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self.model_id = model_id

    def create_observation(
        self,
        segment_id: str,
        source: str,
        zone: Zone | str,
        captured_at: datetime,
        verdict: RoadStatus | str,
        confidence: float = 1.0,
        max_coverage: float | None = None,
        hazard_type: HazardType | str | None = None,
        blocking_hazards: list[str] | None = None,
        visibility: str = "full",
        near_miss: bool = False,
        recovery: bool = False,
        direct_verdict: RoadStatus | str | None = None,
        mapped_verdict: RoadStatus | str | None = None,
        evidence: str | None = None,
    ) -> SegmentObservation:
        """
        Constructs a validated SegmentObservation tagged as mock data.
        """
        zone_enum = Zone(zone) if isinstance(zone, str) else zone
        verdict_enum = RoadStatus(verdict) if isinstance(verdict, str) else verdict
        hazard_enum = HazardType(hazard_type) if isinstance(hazard_type, str) else hazard_type
        dir_v = RoadStatus(direct_verdict) if isinstance(direct_verdict, str) else direct_verdict
        map_v = RoadStatus(mapped_verdict) if isinstance(mapped_verdict, str) else mapped_verdict

        # Near miss safety rule: near-miss hazards do not block the corridor
        if near_miss:
            verdict_enum = RoadStatus.CLEAR
            if max_coverage is None:
                max_coverage = 0.05
            evidence = evidence or "Synthetic hazard detected adjacent to road; no obstruction detected on roadway."

        if evidence is None:
            if verdict_enum == RoadStatus.BLOCKED:
                evidence = f"Synthetic {hazard_enum.value if hazard_enum else 'hazard'} covers >=90% of corridor width."
            elif verdict_enum == RoadStatus.PARTIAL:
                evidence = f"Synthetic {hazard_enum.value if hazard_enum else 'hazard'} covers 30-90% of road width."
            elif verdict_enum == RoadStatus.CLEAR:
                evidence = "No obstruction detected in synthetic scene imagery."
            else:
                evidence = "Ambiguous evidence in synthetic scene."

        return SegmentObservation(
            segment_id=segment_id,
            source=source,
            zone=zone_enum,
            captured_at=captured_at,
            uploaded_at=datetime.now(UTC),
            verdict=verdict_enum,
            confidence=confidence,
            max_coverage=max_coverage,
            hazard_type=hazard_enum,
            blocking_hazards=blocking_hazards or [],
            evidence=evidence,
            visibility=visibility,
            direct_verdict=dir_v,
            mapped_verdict=map_v,
            near_miss=near_miss,
            recovery=recovery,
            model_id=self.model_id,
            is_mock=True,
        )

    def from_scenario_step(
        self,
        raw_obs: dict[str, Any],
        default_zone: Zone | None = None,
    ) -> list[SegmentObservation]:
        """Alias for from_scenario_event_observation for ScenarioPlayer step processing."""
        return self.from_scenario_event_observation(raw_obs, default_zone=default_zone)

    def from_scenario_event_observation(
        self,
        raw_obs: dict[str, Any],
        default_zone: Zone | None = None,
    ) -> list[SegmentObservation]:
        """
        Expands a ScenarioPlayer observation dictionary (covering 1 or more segments)
        into a list of validated SegmentObservation records.
        """
        source = raw_obs.get("source", "synthetic_camera")
        zone_val = raw_obs.get("zone") or (default_zone.value if default_zone else "NW")
        zone = Zone(zone_val)

        # Parse capture timestamp
        cap_time_raw = raw_obs.get("capture_time") or raw_obs.get("captured_at")
        if isinstance(cap_time_raw, str):
            captured_at = datetime.fromisoformat(cap_time_raw)
        elif isinstance(cap_time_raw, datetime):
            captured_at = cap_time_raw
        else:
            captured_at = datetime.now(UTC)

        hazard_str = raw_obs.get("hazard_type")
        hazard_type = HazardType(hazard_str) if hazard_str else None
        near_miss = bool(raw_obs.get("near_miss", False))
        recovery = bool(raw_obs.get("recovery", False))
        affected_segs = raw_obs.get("affected_segments", [])

        confidence = float(raw_obs.get("confidence", 0.65 if recovery else 1.0))
        visibility = str(raw_obs.get("visibility", "partial" if recovery else "full"))

        # Determine verdict based on hazard & flags
        if near_miss:
            # Proximity alone does not block roads, but degraded visibility cannot claim confirmed CLEAR
            if visibility.lower() != "full":
                verdict = RoadStatus.UNCERTAIN
            else:
                verdict = RoadStatus.CLEAR
            max_cov = 0.05
        elif recovery:
            # Recovery initial submission before strong evidence is verified
            verdict = RoadStatus.CLEAR
            max_cov = 0.0
        elif hazard_type is not None:
            verdict = RoadStatus.BLOCKED
            max_cov = 1.0
        else:
            verdict = RoadStatus.CLEAR
            max_cov = 0.0

        results: list[SegmentObservation] = []
        for seg_id in affected_segs:
            obs = self.create_observation(
                segment_id=seg_id,
                source=source,
                zone=zone,
                captured_at=captured_at,
                verdict=verdict,
                confidence=confidence,
                max_coverage=max_cov,
                hazard_type=hazard_type,
                near_miss=near_miss,
                recovery=recovery,
                visibility=visibility,
            )
            results.append(obs)

        return results

    def from_ground_truth(
        self,
        scene: Scene,
        ground_truth: GroundTruth,
        captured_at: datetime,
        source: str = "oracle_camera",
    ) -> list[SegmentObservation]:
        """
        Generates oracle mock observations for all segments using GroundTruth.
        """
        # Map segment ID to zone from scene
        seg_zone_map = {s.id: s.zone for s in scene.road_segments}
        results: list[SegmentObservation] = []

        for sgt in ground_truth.segment_statuses:
            zone = seg_zone_map.get(sgt.segment_id, Zone.NW)
            obs = self.create_observation(
                segment_id=sgt.segment_id,
                source=source,
                zone=zone,
                captured_at=captured_at,
                verdict=sgt.status,
                confidence=1.0,
                max_coverage=sgt.max_coverage,
                blocking_hazards=sgt.blocking_hazards,
                visibility="full",
                near_miss=False,
                recovery=False,
            )
            results.append(obs)

        return results

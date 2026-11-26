import React, { useEffect, useState } from "react";
import {
  CameraView,
  Observation,
  RoadStatus,
  ScenarioData,
  ScenarioEvent,
  SegmentState,
} from "../../types/scene";
import "../scene/scene.css";

export interface ScenarioPlayerProps {
  scenario?: ScenarioData;
  backendApiUrl?: string;
  onObservationSubmitted?: (obs: Observation, currentClock: string) => void;
  onClockChanged?: (
    clockTime: string,
    updatedStates: Record<string, SegmentState>,
  ) => void;
  className?: string;
}

const DEFAULT_DEMO_SCENARIO: ScenarioData = {
  scenario_id: "demo_city",
  description:
    "DisasterLens 6×6 Demonstration City with 4 camera views and T0–T3 observation timeline.",
  grid_size: 6,
  seed: 20261127,
  cameras: [
    {
      camera_id: "synthetic_camera_1",
      zone: "NW",
      viewport: { x_min: 0, y_min: 0, x_max: 512, y_max: 512 },
      covered_segments: ["SEG-001", "SEG-002", "SEG-007", "SEG-008"],
    },
    {
      camera_id: "synthetic_camera_2",
      zone: "NE",
      viewport: { x_min: 512, y_min: 0, x_max: 1024, y_max: 512 },
      covered_segments: ["SEG-003", "SEG-004", "SEG-009", "SEG-010"],
    },
    {
      camera_id: "synthetic_camera_3",
      zone: "SW",
      viewport: { x_min: 0, y_min: 512, x_max: 512, y_max: 1024 },
      covered_segments: ["SEG-031", "SEG-032", "SEG-037", "SEG-038"],
    },
    {
      camera_id: "synthetic_camera_4",
      zone: "SE",
      viewport: { x_min: 512, y_min: 512, x_max: 1024, y_max: 1024 },
      covered_segments: ["SEG-033", "SEG-034", "SEG-039", "SEG-040"],
    },
  ],
  events: [
    {
      time_step: "T0",
      timestamp: null,
      description: "No observations yet. All road statuses UNKNOWN.",
      observations: [],
    },
    {
      time_step: "T1",
      timestamp: "2026-11-27T08:00:00+05:30",
      description:
        "Flood detected across SEG-001. Expected outcome: BLOCKED. Saved route raises an alert.",
      observations: [
        {
          source: "synthetic_camera_1",
          capture_time: "2026-11-27T08:00:00+05:30",
          zone: "NW",
          affected_segments: ["SEG-001"],
          hazard_type: "flood",
          image: "/scenarios/demo_city/camera_1.png",
        },
      ],
    },
    {
      time_step: "T2",
      timestamp: "2026-11-27T09:00:00+05:30",
      description:
        "Debris detected beside SEG-005 (near-miss). Expected outcome: road remains unblocked (CLEAR). No false block.",
      observations: [
        {
          source: "synthetic_camera_2",
          capture_time: "2026-11-27T09:00:00+05:30",
          zone: "NE",
          affected_segments: ["SEG-005"],
          hazard_type: "debris",
          near_miss: true,
          image: "/scenarios/demo_city/camera_2.png",
        },
      ],
    },
    {
      time_step: "T3",
      timestamp: "2026-11-27T10:00:00+05:30",
      description:
        "Same NW corridor (SEG-001) re-observed with flood receded. Recovery requires stronger evidence -> UNCERTAIN.",
      observations: [
        {
          source: "synthetic_camera_1",
          capture_time: "2026-11-27T10:00:00+05:30",
          zone: "NW",
          affected_segments: ["SEG-001"],
          hazard_type: null,
          recovery: true,
          image: "/scenarios/demo_city/camera_1_t3.png",
        },
      ],
    },
  ],
  scene_file: "scene.json",
  ground_truth_file: "ground_truth.json",
};

function formatIstIso(epochMs: number): string {
  const istOffsetMs = 5.5 * 3600 * 1000;
  const d = new Date(epochMs + istOffsetMs);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}+05:30`;
}

function calculateFreshness(
  captureTimeStr: string,
  simulatedClockMs: number,
): { ageHours: number; freshness: "FRESH" | "AGEING" | "STALE" } {
  const cap = new Date(captureTimeStr).getTime();
  const diffHours = Math.max(0, (simulatedClockMs - cap) / (1000 * 60 * 60));

  if (diffHours <= 3) return { ageHours: diffHours, freshness: "FRESH" };
  if (diffHours <= 12) return { ageHours: diffHours, freshness: "AGEING" };
  return { ageHours: diffHours, freshness: "STALE" };
}

export const ScenarioPlayer: React.FC<ScenarioPlayerProps> = ({
  scenario = DEFAULT_DEMO_SCENARIO,
  backendApiUrl = "http://localhost:8000",
  onObservationSubmitted,
  onClockChanged,
  className = "",
}) => {
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [activeCameraId, setActiveCameraId] = useState("synthetic_camera_1");
  const [useLiveApi, setUseLiveApi] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [apiSuccess, setApiSuccess] = useState<string | null>(null);
  const [simulatedHourOffset, setSimulatedHourOffset] = useState(0);
  const [submittedObservations, setSubmittedObservations] = useState<
    Observation[]
  >([]);

  const baseTimeMs = new Date("2026-11-27T08:00:00+05:30").getTime();
  const currentClockMs = baseTimeMs + simulatedHourOffset * 3600 * 1000;
  const simulatedClockIso = formatIstIso(currentClockMs);

  const currentEvent: ScenarioEvent =
    scenario.events[currentStepIdx] || scenario.events[0];
  const activeCamera: CameraView =
    scenario.cameras.find((c) => c.camera_id === activeCameraId) ||
    scenario.cameras[0];

  useEffect(() => {
    const updatedStates: Record<string, SegmentState> = {};

    submittedObservations.forEach((obs) => {
      const { ageHours, freshness } = calculateFreshness(
        obs.capture_time,
        currentClockMs,
      );
      let status: RoadStatus = "unknown";

      if (obs.near_miss) {
        status = freshness === "STALE" ? "stale" : "clear";
      } else if (obs.recovery) {
        status = ageHours > 12 ? "unknown" : "uncertain";
      } else if (obs.hazard_type === "flood" || obs.hazard_type === "debris") {
        status = ageHours > 24 ? "stale" : "blocked";
      } else {
        status = freshness === "STALE" ? "stale" : "clear";
      }

      obs.affected_segments.forEach((segId) => {
        updatedStates[segId] = {
          segment_id: segId,
          status,
          captured_at: obs.capture_time,
          age_hours: ageHours,
          source: obs.source,
        };
      });
    });

    onClockChanged?.(simulatedClockIso, updatedStates);
  }, [
    simulatedHourOffset,
    submittedObservations,
    currentClockMs,
    simulatedClockIso,
  ]);

  const handleSubmitObservation = async () => {
    if (isSubmitting) return;
    const nextIdx = currentStepIdx + 1;
    if (nextIdx >= scenario.events.length) {
      setApiError("All scenario events (T0–T3) have already been submitted.");
      return;
    }

    const nextEvent = scenario.events[nextIdx];
    if (!nextEvent.observations.length) {
      setApiError("Selected event contains no observations to submit.");
      setCurrentStepIdx(nextIdx);
      return;
    }

    const obsToSubmit = nextEvent.observations[0];
    if (!obsToSubmit.source || !obsToSubmit.capture_time) {
      setApiError(
        "Invalid observation payload: missing source or capture_time.",
      );
      return;
    }

    setIsSubmitting(true);
    setApiError(null);
    setApiSuccess(null);

    if (useLiveApi) {
      try {
        const resp = await fetch(`${backendApiUrl}/api/observations`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(obsToSubmit),
        });
        if (!resp.ok) {
          throw new Error(
            `Backend API returned HTTP ${resp.status}: ${resp.statusText}`,
          );
        }
        await resp.json();
        setApiSuccess(
          `Live API accepted observation from ${obsToSubmit.source}.`,
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setApiError(
          `Backend API failure: ${msg}. Switch to Local Simulation Mode or start the backend server.`,
        );
        setIsSubmitting(false);
        return;
      }
    } else {
      setApiSuccess(
        `[Local Simulation Adapter] Observation ingested from ${obsToSubmit.source}.`,
      );
    }

    setIsSubmitting(false);
    setCurrentStepIdx(nextIdx);
    setSubmittedObservations((prev) => [...prev, obsToSubmit]);
    onObservationSubmitted?.(obsToSubmit, simulatedClockIso);

    const cam = scenario.cameras.find(
      (c) => c.camera_id === obsToSubmit.source,
    );
    if (cam) setActiveCameraId(cam.camera_id);
  };

  const handleReset = () => {
    setCurrentStepIdx(0);
    setSubmittedObservations([]);
    setSimulatedHourOffset(0);
    setApiError(null);
    setApiSuccess("Timeline reset to T0 (all roads UNKNOWN).");
  };

  const activeObs = currentEvent.observations[0];
  const camNum = activeCamera.camera_id.split("_").pop() ?? "1";
  const cameraImageSrc =
    activeObs?.source === activeCamera.camera_id && activeObs.image
      ? activeObs.image.startsWith("/")
        ? activeObs.image
        : `/scenarios/demo_city/${activeObs.image}`
      : `/scenarios/demo_city/camera_${camNum}.png`;

  return (
    <div className={`dl-player-card ${className}`}>
      <div className="dl-player-head">
        <div>
          <h2>Scenario Timeline Player</h2>
          <p>6×6 Demo City · 4 Camera Views · T0–T3 Evolution</p>
        </div>

        <div className="dl-mode-switch" role="group" aria-label="Backend mode">
          <button
            type="button"
            onClick={() => setUseLiveApi(false)}
            className={`dl-mode-btn ${!useLiveApi ? "active" : ""}`}
          >
            Local Simulation
          </button>
          <button
            type="button"
            onClick={() => setUseLiveApi(true)}
            className={`dl-mode-btn ${useLiveApi ? "active" : ""}`}
          >
            Live Backend
          </button>
        </div>
      </div>

      <div className="dl-steps-grid">
        {scenario.events.map((evt, idx) => {
          const isActive = idx === currentStepIdx;
          const isPassed = idx < currentStepIdx;
          return (
            <button
              type="button"
              key={evt.time_step}
              onClick={() => setCurrentStepIdx(idx)}
              className={`dl-step-btn ${isActive ? "active" : isPassed ? "passed" : ""}`}
            >
              <span className="dl-step-code">{evt.time_step}</span>
              <span style={{ fontSize: 10 }}>
                {evt.timestamp
                  ? evt.timestamp.slice(11, 16) + " IST"
                  : "Baseline"}
              </span>
            </button>
          );
        })}
      </div>

      <div className="dl-box">
        <div className="dl-box-row">
          <strong>Step {currentEvent.time_step}</strong>
          <span style={{ fontFamily: "monospace", color: "#65776c" }}>
            {currentEvent.timestamp ?? "No observations"}
          </span>
        </div>
        <p style={{ fontSize: 12, color: "#2d3b33", lineHeight: 1.45 }}>
          {currentEvent.description}
        </p>
        {activeObs && (
          <div style={{ fontSize: 11, color: "#55665c", marginTop: 4 }}>
            Source: <code>{activeObs.source}</code> · Zone{" "}
            <strong>{activeObs.zone}</strong> · Affected:{" "}
            <code>{activeObs.affected_segments.join(", ") || "None"}</code>
          </div>
        )}
      </div>

      <div className="dl-box">
        <div className="dl-box-row">
          <strong>Simulated System Clock (+05:30 IST)</strong>
          <span
            style={{
              fontFamily: "monospace",
              fontWeight: 700,
              color: "#297b59",
            }}
          >
            {simulatedClockIso} (+{simulatedHourOffset}h)
          </span>
        </div>
        <input
          type="range"
          min="0"
          max="26"
          step="0.5"
          value={simulatedHourOffset}
          onChange={(e) => setSimulatedHourOffset(parseFloat(e.target.value))}
          aria-label="Simulated clock slider"
          className="dl-clock-slider"
        />
        <div className="dl-clock-ticks">
          <span>+0h (08:00)</span>
          <span>+3h (Fresh limit)</span>
          <span>+12h (Stale clear)</span>
          <span>+24h (Stale block)</span>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="dl-box-row">
          <strong style={{ fontSize: 11 }}>
            Camera View ({activeCamera.zone})
          </strong>
          <span
            style={{ fontFamily: "monospace", fontSize: 10, color: "#65776c" }}
          >
            {activeCamera.camera_id}
          </span>
        </div>
        <div className="dl-cam-grid">
          {scenario.cameras.map((cam) => (
            <button
              type="button"
              key={cam.camera_id}
              onClick={() => setActiveCameraId(cam.camera_id)}
              className={`dl-cam-btn ${cam.camera_id === activeCameraId ? "active" : ""}`}
            >
              <span style={{ fontFamily: "monospace", fontWeight: 700 }}>
                {cam.camera_id}
              </span>
              <span style={{ fontSize: 10, color: "#65776c" }}>
                Zone {cam.zone} · {cam.covered_segments.length} segments
              </span>
            </button>
          ))}
        </div>
        <img
          src={cameraImageSrc}
          alt={`${activeCamera.camera_id} feed`}
          className="dl-cam-preview"
        />
      </div>

      {apiError && <div className="dl-alert-err">{apiError}</div>}
      {apiSuccess && <div className="dl-alert-ok">{apiSuccess}</div>}

      <div className="dl-actions-row">
        <button
          type="button"
          onClick={handleSubmitObservation}
          disabled={
            isSubmitting || currentStepIdx >= scenario.events.length - 1
          }
          className="dl-primary-btn"
        >
          {isSubmitting
            ? "Submitting observation…"
            : currentStepIdx >= scenario.events.length - 1
              ? "Scenario Replay Complete (T3)"
              : `Submit Next Observation (T${currentStepIdx + 1})`}
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="secondary-button"
        >
          Reset
        </button>
      </div>

      <div style={{ borderTop: "1px solid #edf1ee", paddingTop: 10 }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            marginBottom: 6,
            color: "#46564c",
          }}
        >
          Observation History ({submittedObservations.length})
        </div>
        {submittedObservations.length === 0 ? (
          <div style={{ fontSize: 11, color: "#849089" }}>
            No observations submitted yet.
          </div>
        ) : (
          <div className="dl-history-list">
            {submittedObservations.map((obs, idx) => (
              <div key={idx} className="dl-history-item">
                <span>
                  <code>{obs.source}</code> ({obs.zone})
                </span>
                <span>
                  <code>{obs.affected_segments.join(", ")}</code> ·{" "}
                  {obs.capture_time.slice(11, 16)} IST
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ScenarioPlayer;

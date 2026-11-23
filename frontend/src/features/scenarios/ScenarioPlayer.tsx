import React, { useState, useEffect } from 'react';
import {
  CameraView,
  Observation,
  RoadStatus,
  ScenarioData,
  ScenarioEvent,
  SegmentState,
} from '../../types/scene';
import {
  Clock,
  RotateCcw,
  Send,
  AlertCircle,
  CheckCircle2,
  Camera,
  Server,
  Radio,
} from 'lucide-react';

export interface ScenarioPlayerProps {
  scenario?: ScenarioData;
  backendApiUrl?: string;
  onObservationSubmitted?: (obs: Observation, currentClock: string) => void;
  onClockChanged?: (clockTime: string, updatedStates: Record<string, SegmentState>) => void;
  className?: string;
}

// Built-in fixture data for demo city if scenario prop not provided
const DEFAULT_DEMO_SCENARIO: ScenarioData = {
  scenario_id: 'demo_city',
  description:
    'DisasterLens 6×6 Demonstration City with 4 camera views and T0–T3 observation timeline.',
  grid_size: 6,
  seed: 20261127,
  cameras: [
    {
      camera_id: 'synthetic_camera_1',
      zone: 'NW',
      viewport: { x_min: 0, y_min: 0, x_max: 512, y_max: 512 },
      covered_segments: ['SEG-001', 'SEG-002', 'SEG-007', 'SEG-008'],
    },
    {
      camera_id: 'synthetic_camera_2',
      zone: 'NE',
      viewport: { x_min: 512, y_min: 0, x_max: 1024, y_max: 512 },
      covered_segments: ['SEG-003', 'SEG-004', 'SEG-009', 'SEG-010'],
    },
    {
      camera_id: 'synthetic_camera_3',
      zone: 'SW',
      viewport: { x_min: 0, y_min: 512, x_max: 512, y_max: 1024 },
      covered_segments: ['SEG-031', 'SEG-032', 'SEG-037', 'SEG-038'],
    },
    {
      camera_id: 'synthetic_camera_4',
      zone: 'SE',
      viewport: { x_min: 512, y_min: 512, x_max: 1024, y_max: 1024 },
      covered_segments: ['SEG-033', 'SEG-034', 'SEG-039', 'SEG-040'],
    },
  ],
  events: [
    {
      time_step: 'T0',
      timestamp: null,
      description: 'Initial state: No observations yet. All road statuses UNKNOWN.',
      observations: [],
    },
    {
      time_step: 'T1',
      timestamp: '2026-11-27T08:00:00+05:30',
      description:
        'Flood detected across main NW corridor. Expected status: BLOCKED. Route alerts trigger.',
      observations: [
        {
          source: 'synthetic_camera_1',
          capture_time: '2026-11-27T08:00:00+05:30',
          zone: 'NW',
          affected_segments: ['SEG-001', 'SEG-007'],
          hazard_type: 'flood',
          image: '/scenarios/demo_city/camera_1.png',
        },
      ],
    },
    {
      time_step: 'T2',
      timestamp: '2026-11-27T09:00:00+05:30',
      description:
        'Debris detected beside road in NE (near-miss decoy). Expected: road remains CLEAR. No false block.',
      observations: [
        {
          source: 'synthetic_camera_2',
          capture_time: '2026-11-27T09:00:00+05:30',
          zone: 'NE',
          affected_segments: ['SEG-003'],
          hazard_type: 'debris',
          near_miss: true,
          image: '/scenarios/demo_city/camera_2.png',
        },
      ],
    },
    {
      time_step: 'T3',
      timestamp: '2026-11-27T10:00:00+05:30',
      description:
        'NW flood area re-imaged with floodwaters receded. Recovery requires verification -> UNCERTAIN.',
      observations: [
        {
          source: 'synthetic_camera_1',
          capture_time: '2026-11-27T10:00:00+05:30',
          zone: 'NW',
          affected_segments: ['SEG-001', 'SEG-007'],
          hazard_type: null,
          recovery: true,
          image: '/scenarios/demo_city/camera_1.png',
        },
      ],
    },
  ],
  scene_file: 'scene.json',
  ground_truth_file: 'ground_truth.json',
};

// Calculate simulated freshness
function calculateFreshness(captureTimeStr: string, simulatedClockStr: string) {
  const cap = new Date(captureTimeStr).getTime();
  const sim = new Date(simulatedClockStr).getTime();
  const diffHours = (sim - cap) / (1000 * 60 * 60);

  if (diffHours < 0) return { ageHours: 0, status: 'FRESH' as const };
  if (diffHours <= 3) return { ageHours: diffHours, status: 'FRESH' as const };
  if (diffHours <= 12) return { ageHours: diffHours, status: 'AGEING' as const };
  return { ageHours: diffHours, status: 'STALE' as const };
}

export const ScenarioPlayer: React.FC<ScenarioPlayerProps> = ({
  scenario = DEFAULT_DEMO_SCENARIO,
  backendApiUrl = 'http://localhost:8000',
  onObservationSubmitted,
  onClockChanged,
  className = '',
}) => {
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [activeCameraId, setActiveCameraId] = useState('synthetic_camera_1');
  const [useLiveApi, setUseLiveApi] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [apiSuccess, setApiSuccess] = useState<string | null>(null);

  // Simulated clock (hours from 08:00 IST on 2026-11-27)
  // Range: 0 hours (08:00) to 24 hours (next day 08:00)
  const [simulatedHourOffset, setSimulatedHourOffset] = useState(0);

  const baseTime = new Date('2026-11-27T08:00:00+05:30').getTime();
  const currentSimulatedTime = new Date(baseTime + simulatedHourOffset * 3600 * 1000);
  const simulatedClockIso = currentSimulatedTime.toISOString().replace('Z', '+05:30');

  // Observation submission history
  const [submittedObservations, setSubmittedObservations] = useState<Observation[]>([]);

  // Current event
  const currentEvent: ScenarioEvent = scenario.events[currentStepIdx] || scenario.events[0];
  const activeCamera: CameraView =
    scenario.cameras.find((c) => c.camera_id === activeCameraId) || scenario.cameras[0];

  // Notify parent on clock change
  useEffect(() => {
    // Recompute road states based on submitted observations and current simulated clock
    const updatedStates: Record<string, SegmentState> = {};

    submittedObservations.forEach((obs) => {
      const freshness = calculateFreshness(obs.capture_time, simulatedClockIso);
      let status: RoadStatus = 'UNKNOWN';

      if (obs.hazard_type === 'flood' || obs.hazard_type === 'debris') {
        if (obs.near_miss) {
          status = 'CLEAR';
        } else {
          status = freshness.status === 'STALE' ? 'STALE' : 'BLOCKED';
        }
      } else if (obs.recovery) {
        status = 'UNCERTAIN';
      } else {
        status = freshness.status === 'STALE' ? 'STALE' : 'CLEAR';
      }

      obs.affected_segments.forEach((segId) => {
        updatedStates[segId] = {
          segment_id: segId,
          status,
          captured_at: obs.capture_time,
          source: obs.source,
        };
      });
    });

    onClockChanged?.(simulatedClockIso, updatedStates);
  }, [simulatedHourOffset, submittedObservations]);

  // Submit next observation
  const handleSubmitObservation = async () => {
    const nextIdx = currentStepIdx + 1;
    if (nextIdx >= scenario.events.length) {
      setApiError('All scenario events (T0–T3) have been submitted.');
      return;
    }

    const nextEvent = scenario.events[nextIdx];
    if (nextEvent.observations.length === 0) {
      setCurrentStepIdx(nextIdx);
      return;
    }

    const obsToSubmit = nextEvent.observations[0];
    setIsSubmitting(true);
    setApiError(null);
    setApiSuccess(null);

    if (useLiveApi) {
      try {
        const resp = await fetch(`${backendApiUrl}/api/observations`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(obsToSubmit),
        });

        if (!resp.ok) {
          throw new Error(`Backend API returned HTTP ${resp.status}: ${resp.statusText}`);
        }
        await resp.json();
        setApiSuccess(`Live observation ingested via ${obsToSubmit.source}`);
      } catch (err: any) {
        setApiError(`API Failure: ${err.message}. Check if Rajneesh's backend is running.`);
        setIsSubmitting(false);
        return; // Don't advance on live API failure
      }
    } else {
      // Mock / local simulation adapter
      setApiSuccess(`[Local Mock Mode] Observation ingested for ${obsToSubmit.source}`);
    }

    setIsSubmitting(false);
    setCurrentStepIdx(nextIdx);
    setSubmittedObservations((prev) => [...prev, obsToSubmit]);
    onObservationSubmitted?.(obsToSubmit, simulatedClockIso);

    // Auto-select the camera view for this observation
    const cam = scenario.cameras.find((c) => c.camera_id === obsToSubmit.source);
    if (cam) setActiveCameraId(cam.camera_id);
  };

  const handleReset = () => {
    setCurrentStepIdx(0);
    setSubmittedObservations([]);
    setSimulatedHourOffset(0);
    setApiError(null);
    setApiSuccess('Timeline reset to T0.');
  };

  return (
    <div className={`bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-2xl flex flex-col gap-5 ${className}`}>
      {/* Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Radio className="w-5 h-5 text-sky-400 animate-pulse" />
            <h2 className="text-lg font-bold text-slate-100">Scenario Timeline Player</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            6×6 Demo City • 4 Autonomous Camera Feeds • T0–T3 Disaster Evolution
          </p>
        </div>

        {/* Backend mode switch */}
        <div className="flex items-center gap-2 bg-slate-950 p-1.5 rounded-lg border border-slate-800 text-xs">
          <Server className="w-4 h-4 text-slate-400" />
          <span className="text-slate-400">Mode:</span>
          <button
            onClick={() => setUseLiveApi(false)}
            className={`px-2.5 py-1 rounded font-medium transition ${
              !useLiveApi ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}
          >
            Local Mock
          </button>
          <button
            onClick={() => setUseLiveApi(true)}
            className={`px-2.5 py-1 rounded font-medium transition ${
              useLiveApi ? 'bg-emerald-600 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}
          >
            Live Backend
          </button>
        </div>
      </div>

      {/* T0–T3 Stepper */}
      <div className="grid grid-cols-4 gap-2">
        {scenario.events.map((evt, idx) => {
          const isActive = idx === currentStepIdx;
          const isPassed = idx < currentStepIdx;
          return (
            <div
              key={evt.time_step}
              onClick={() => setCurrentStepIdx(idx)}
              className={`p-3 rounded-lg border cursor-pointer transition flex flex-col gap-1 ${
                isActive
                  ? 'bg-sky-950/70 border-sky-500 shadow-md ring-1 ring-sky-500/50'
                  : isPassed
                  ? 'bg-slate-800/60 border-slate-700 text-slate-300'
                  : 'bg-slate-900/40 border-slate-800 text-slate-500 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className={`font-mono font-bold text-sm ${isActive ? 'text-sky-400' : ''}`}>
                  {evt.time_step}
                </span>
                {isPassed && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
              </div>
              <span className="text-[11px] truncate text-slate-300">
                {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Initial'}
              </span>
            </div>
          );
        })}
      </div>

      {/* Current Step Description Card */}
      <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-4 flex flex-col gap-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-semibold text-sky-400">Step {currentEvent.time_step} Overview</span>
          <span className="text-slate-500">
            {currentEvent.timestamp ? `${currentEvent.timestamp}` : 'Baseline State'}
          </span>
        </div>
        <p className="text-sm text-slate-200">{currentEvent.description}</p>

        {currentEvent.observations.length > 0 && (
          <div className="mt-2 bg-slate-900/90 border border-slate-800/80 rounded p-2.5 text-xs space-y-1">
            <div className="flex items-center justify-between text-slate-400 font-mono text-[11px]">
              <span>Camera Feed: {currentEvent.observations[0].source}</span>
              <span>Zone: {currentEvent.observations[0].zone}</span>
            </div>
            <div className="text-slate-300">
              Affected segments:{' '}
              <span className="font-mono text-amber-300">
                {currentEvent.observations[0].affected_segments.join(', ') || 'None'}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Simulated Clock Slider */}
      <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 text-slate-300 font-medium">
            <Clock className="w-4 h-4 text-amber-400" />
            <span>Simulated System Clock (IST):</span>
          </div>
          <span className="font-mono text-sm font-bold text-amber-300 bg-amber-950/50 px-2.5 py-0.5 rounded border border-amber-600/40">
            {currentSimulatedTime.toLocaleTimeString()} (+{simulatedHourOffset}h elapsed)
          </span>
        </div>

        <div className="space-y-1">
          <input
            type="range"
            min="0"
            max="24"
            step="0.5"
            value={simulatedHourOffset}
            onChange={(e) => setSimulatedHourOffset(parseFloat(e.target.value))}
            className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500"
          />
          <div className="flex justify-between text-[10px] text-slate-500 font-mono">
            <span>T1 (08:00)</span>
            <span>+6h (14:00 - Fresh)</span>
            <span>+12h (20:00 - Ageing)</span>
            <span>+24h (Next day - STALE)</span>
          </div>
        </div>
      </div>

      {/* Camera Feeds & Viewport Selector */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
            <Camera className="w-4 h-4 text-sky-400" />
            <span>Select Autonomous Camera View:</span>
          </div>
          <span className="text-[11px] text-slate-500 font-mono">
            Active: {activeCamera.camera_id} ({activeCamera.zone})
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {scenario.cameras.map((cam) => {
            const isSelected = cam.camera_id === activeCameraId;
            return (
              <button
                key={cam.camera_id}
                onClick={() => setActiveCameraId(cam.camera_id)}
                className={`p-2.5 rounded-lg border text-xs text-left transition flex flex-col gap-1 ${
                  isSelected
                    ? 'bg-sky-950/80 border-sky-500 text-sky-200'
                    : 'bg-slate-950/50 border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <span className="font-mono font-semibold">{cam.camera_id}</span>
                <span className="text-[10px] text-slate-400">
                  Zone {cam.zone} • {cam.covered_segments.length} Segments
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Status Messages */}
      {apiError && (
        <div className="bg-red-950/50 border border-red-600/50 text-red-300 p-3 rounded-lg text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
          <span>{apiError}</span>
        </div>
      )}
      {apiSuccess && (
        <div className="bg-emerald-950/40 border border-emerald-600/40 text-emerald-300 p-2.5 rounded-lg text-xs flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
          <span>{apiSuccess}</span>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={handleSubmitObservation}
          disabled={isSubmitting || currentStepIdx >= scenario.events.length - 1}
          className="flex-1 bg-sky-600 hover:bg-sky-500 disabled:bg-slate-800 disabled:text-slate-600 text-white font-medium py-2.5 px-4 rounded-lg text-sm transition flex items-center justify-center gap-2 shadow-lg disabled:cursor-not-allowed"
        >
          {isSubmitting ? (
            <span className="animate-spin mr-2">◌</span>
          ) : (
            <Send className="w-4 h-4" />
          )}
          <span>
            {currentStepIdx >= scenario.events.length - 1
              ? 'Scenario Replay Complete'
              : `Submit Next Observation (Step T${currentStepIdx + 1})`}
          </span>
        </button>

        <button
          onClick={handleReset}
          className="bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium py-2.5 px-4 rounded-lg text-sm transition flex items-center gap-1.5 border border-slate-700"
          title="Reset scenario timeline"
        >
          <RotateCcw className="w-4 h-4" />
          <span>Reset</span>
        </button>
      </div>

      {/* Observation History */}
      <div className="border-t border-slate-800 pt-3">
        <span className="text-xs font-semibold text-slate-400">
          Observation History ({submittedObservations.length} ingested):
        </span>
        {submittedObservations.length === 0 ? (
          <p className="text-slate-500 text-xs italic mt-1">No observations submitted yet.</p>
        ) : (
          <div className="mt-2 space-y-1.5 max-h-36 overflow-y-auto pr-1">
            {submittedObservations.map((obs, i) => (
              <div
                key={i}
                className="bg-slate-950/50 border border-slate-800/80 rounded px-2.5 py-1.5 text-xs flex items-center justify-between text-slate-300"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sky-400 font-semibold">{obs.source}</span>
                  <span className="text-slate-400 text-[10px]">Zone {obs.zone}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[11px] text-amber-300">
                    {obs.affected_segments.join(', ')}
                  </span>
                  <span className="text-slate-500 text-[10px]">
                    {new Date(obs.capture_time).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
export default ScenarioPlayer;

import React, { useState, useEffect } from 'react';
import { SafetyBanner } from './components/SafetyBanner';
import { SceneCanvas } from './features/scene/SceneCanvas';
import { ScenarioPlayer } from './features/scenarios/ScenarioPlayer';
import { RouteScreen } from './features/routing/RouteScreen';
import {
  SegmentState,
  SceneData,
  Observation,
  RoadStatus,
} from './types/scene';
import {
  Compass,
  Layers,
  Navigation,
  PlaySquare,
} from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'routing' | 'demo' | 'benchmark'>('routing');
  const [clockIso, setClockIso] = useState('2026-11-27T08:00:00+05:30');
  const [demoStates, setDemoStates] = useState<Record<string, SegmentState>>({});
  const [selectedRoute, setSelectedRoute] = useState<string[]>(['SEG-001', 'SEG-002']);

  // Demo city data (loaded from scenarios/demo_city or fallback)
  const [demoScene, setDemoScene] = useState<SceneData | null>(null);

  // Benchmark browser state
  const [selectedSceneId, setSelectedSceneId] = useState('S-0001');
  const [benchmarkScene, setBenchmarkScene] = useState<SceneData | null>(null);
  const [benchmarkStates, setBenchmarkStates] = useState<Record<string, SegmentState>>({});

  useEffect(() => {
    // Attempt to load demo city scene.json
    fetch('/scenarios/demo_city/scene.json')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setDemoScene(data);
      })
      .catch(() => {});

    // Attempt to load benchmark scene.json
    fetch(`/datasets/v1/${selectedSceneId}/scene.json`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setBenchmarkScene(data);
      })
      .catch(() => {});

    // Attempt to load ground truth
    fetch(`/datasets/v1/${selectedSceneId}/ground_truth.json`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && data.segment_statuses) {
          const st: Record<string, SegmentState> = {};
          data.segment_statuses.forEach((s: any) => {
            st[s.segment_id] = s;
          });
          setBenchmarkStates(st);
        }
      })
      .catch(() => {});
  }, [selectedSceneId]);

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      {/* Mandatory Safety Banner */}
      <SafetyBanner />

      {/* Main Header */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 py-3.5 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-sky-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-sky-500/20">
              <Compass className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-bold text-base sm:text-lg text-white">DisasterLens</h1>
                <span className="text-[10px] font-mono bg-sky-500/10 text-sky-400 border border-sky-500/20 px-1.5 py-0.5 rounded">
                  v1.0 Benchmark & Navigation
                </span>
              </div>
              <p className="text-[11px] text-slate-400">
                Visual Task Factory • Road Obstruction Routing & Scene Evaluation
              </p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
            <button
              onClick={() => setActiveTab('routing')}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
                activeTab === 'routing'
                  ? 'bg-sky-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Navigation className="w-3.5 h-3.5" />
              Route Screen
            </button>
            <button
              onClick={() => setActiveTab('demo')}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
                activeTab === 'demo'
                  ? 'bg-sky-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <PlaySquare className="w-3.5 h-3.5" />
              Demo City (T0–T3)
            </button>
            <button
              onClick={() => setActiveTab('benchmark')}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
                activeTab === 'benchmark'
                  ? 'bg-sky-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              Benchmark Viewer
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 flex flex-col gap-6">
        {activeTab === 'routing' ? (
          <RouteScreen />
        ) : activeTab === 'demo' ? (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            <div className="lg:col-span-12 bg-slate-900/80 border border-slate-800 px-4 py-2.5 rounded-xl flex items-center justify-between">
              <span className="text-xs font-medium text-slate-300">
                Simulation Clock: <span className="font-mono text-sky-400 font-semibold">{clockIso}</span>
              </span>
              <span className="text-[11px] text-slate-500 font-mono">
                Active Segment Overrides: {Object.keys(demoStates).length}
              </span>
            </div>

            <div className="lg:col-span-7 flex flex-col gap-4">
              <SceneCanvas
                sceneImageUrl="/scenarios/demo_city/image_plain.png"
                segments={demoScene?.road_segments || []}
                intersections={demoScene?.intersections || []}
                buildings={demoScene?.buildings || []}
                hazards={demoScene?.hazards || []}
                segmentStates={demoStates}
                selectedRoutePath={selectedRoute}
                onSegmentClick={(sid) => {
                  setSelectedRoute((prev) =>
                    prev.includes(sid) ? prev.filter((id) => id !== sid) : [...prev, sid]
                  );
                }}
              />
            </div>

            <div className="lg:col-span-5 flex flex-col gap-4">
              <ScenarioPlayer
                onObservationSubmitted={(obs: Observation, newClock: string) => {
                  setClockIso(newClock);
                  const updated: Record<string, SegmentState> = {};
                  const status: RoadStatus = obs.recovery ? 'CLEAR' : (obs.hazard_type ? 'BLOCKED' : 'CLEAR');
                  obs.affected_segments.forEach((sid) => {
                    updated[sid] = {
                      segment_id: sid,
                      status: status,
                      confidence: 1.0,
                      source: obs.source,
                      captured_at: obs.capture_time || newClock,
                    };
                  });
                  setDemoStates((prev) => ({
                    ...prev,
                    ...updated,
                  }));
                }}
                onClockChanged={(newClock, updatedStates) => {
                  setClockIso(newClock);
                  if (Object.keys(updatedStates).length > 0) {
                    setDemoStates(updatedStates);
                  }
                }}
              />
            </div>
          </div>
        ) : (
          /* Benchmark Scene Viewer Tab */
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            <div className="lg:col-span-8 flex flex-col gap-4">
              <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold text-slate-300">Select Scene:</span>
                  <select
                    value={selectedSceneId}
                    onChange={(e) => setSelectedSceneId(e.target.value)}
                    className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs font-mono text-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-500"
                  >
                    {Array.from({ length: 20 }, (_, i) => {
                      const id = `S-${String(i + 1).padStart(4, '0')}`;
                      return (
                        <option key={id} value={id}>
                          {id} {i < 6 ? '(Easy)' : i < 13 ? '(Medium)' : '(Hard)'}
                        </option>
                      );
                    })}
                  </select>
                </div>
              </div>

              <SceneCanvas
                sceneImageUrl={`/datasets/v1/${selectedSceneId}/image_plain.png`}
                segments={benchmarkScene?.road_segments || []}
                intersections={benchmarkScene?.intersections || []}
                buildings={benchmarkScene?.buildings || []}
                hazards={benchmarkScene?.hazards || []}
                segmentStates={benchmarkStates}
              />
            </div>

            <div className="lg:col-span-4 flex flex-col gap-4">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-4">
                <h3 className="font-bold text-sm text-slate-200 border-b border-slate-800 pb-2">
                  Scene Ground Truth Details
                </h3>

                <div className="space-y-2 text-xs">
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Total Intersections:</span>
                    <span className="font-mono text-slate-200">
                      {benchmarkScene?.intersections?.length || 0}
                    </span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Total Road Segments:</span>
                    <span className="font-mono text-slate-200">
                      {benchmarkScene?.road_segments?.length || 0}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-4 px-6 text-center text-xs text-slate-500">
        DisasterLens Visual Task Factory • Synthetic Data & Benchmark Prototype • November 2026
      </footer>
    </div>
  );
};

export default App;

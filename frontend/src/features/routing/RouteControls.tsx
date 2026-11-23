import React from 'react';
import {
  ArrowUpDown,
  Navigation,
  Clock,
  Play,
  RotateCcw,
  AlertCircle,
} from 'lucide-react';
import { CityDetails, ScenarioDetails } from './types';

interface RouteControlsProps {
  city: CityDetails | null;
  origin: string;
  destination: string;
  onOriginChange: (val: string) => void;
  onDestinationChange: (val: string) => void;
  onSwapNodes: () => void;
  onCalculateRoute: () => void;
  isCalculating: boolean;
  scenario: ScenarioDetails | null;
  onAdvanceScenario: (timeStep?: string) => void;
  isAdvancing: boolean;
  clockTime: string | null;
  clockMode: 'simulated' | 'wall-clock';
  error: string | null;
}

export const RouteControls: React.FC<RouteControlsProps> = ({
  city,
  origin,
  destination,
  onOriginChange,
  onDestinationChange,
  onSwapNodes,
  onCalculateRoute,
  isCalculating,
  scenario,
  onAdvanceScenario,
  isAdvancing,
  clockTime,
  clockMode,
  error,
}) => {
  const intersections = city?.intersections || [];
  const currentStep = scenario?.current_time_step || 'T0';

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Navigation className="w-4 h-4 text-sky-400" />
          <h2 className="text-sm font-bold text-white">Route Navigation Engine</h2>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          <span className="font-mono text-slate-300">
            {clockTime ? new Date(clockTime).toLocaleTimeString() : 'Live'}
          </span>
          <span
            className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
              clockMode === 'simulated'
                ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            }`}
          >
            {clockMode}
          </span>
        </div>
      </div>

      {/* Origin / Destination Controls */}
      <div className="grid grid-cols-1 sm:grid-cols-11 gap-2 items-center">
        {/* Origin */}
        <div className="sm:col-span-5 space-y-1">
          <label className="text-[11px] font-semibold text-slate-400 flex items-center justify-between">
            <span>Origin Node</span>
            <span className="text-[10px] font-mono text-slate-500">e.g. N1</span>
          </label>
          <select
            value={origin}
            onChange={(e) => onOriginChange(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-sky-300 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            <option value="">Select origin...</option>
            {intersections.map((node) => (
              <option key={`orig-${node.id}`} value={node.id}>
                {node.id} (Zone {node.zone})
              </option>
            ))}
          </select>
        </div>

        {/* Swap Button */}
        <div className="sm:col-span-1 flex justify-center pt-4 sm:pt-3">
          <button
            type="button"
            onClick={onSwapNodes}
            title="Swap Origin and Destination"
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
          >
            <ArrowUpDown className="w-4 h-4" />
          </button>
        </div>

        {/* Destination */}
        <div className="sm:col-span-5 space-y-1">
          <label className="text-[11px] font-semibold text-slate-400 flex items-center justify-between">
            <span>Destination Node</span>
            <span className="text-[10px] font-mono text-slate-500">e.g. N36</span>
          </label>
          <select
            value={destination}
            onChange={(e) => onDestinationChange(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-sky-300 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            <option value="">Select destination...</option>
            {intersections.map((node) => (
              <option key={`dest-${node.id}`} value={node.id}>
                {node.id} (Zone {node.zone})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Calculate Button */}
      <button
        onClick={onCalculateRoute}
        disabled={isCalculating || !origin || !destination}
        className="w-full py-2.5 px-4 rounded-lg bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed font-semibold text-xs text-white shadow-lg shadow-sky-500/20 flex items-center justify-center gap-2 transition"
      >
        <Navigation className="w-3.5 h-3.5" />
        {isCalculating ? 'Computing Condition-Aware Route...' : 'Calculate Route Recommendation'}
      </button>

      {/* Error Message */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-2.5 flex items-start gap-2 text-xs text-red-300">
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Scenario Timeline Controls */}
      <div className="border-t border-slate-800 pt-3 space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-semibold text-slate-300">Disaster Scenario Timeline</span>
          <span className="font-mono text-sky-400 text-[11px]">
            Step: <strong className="text-white">{currentStep}</strong>
          </span>
        </div>

        {/* Step Buttons */}
        <div className="grid grid-cols-4 gap-1.5">
          {['T0', 'T1', 'T2', 'T3'].map((step) => {
            const isActive = currentStep === step;
            return (
              <button
                key={step}
                onClick={() => onAdvanceScenario(step)}
                disabled={isAdvancing}
                className={`py-1.5 px-2 rounded-lg text-xs font-mono font-semibold transition border ${
                  isActive
                    ? 'bg-sky-600 text-white border-sky-400 shadow-md'
                    : 'bg-slate-950 text-slate-400 border-slate-800 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {step}
              </button>
            );
          })}
        </div>

        {/* Auto Advance Next Step */}
        <div className="flex items-center justify-between pt-1">
          <button
            onClick={() => onAdvanceScenario()}
            disabled={isAdvancing}
            className="flex items-center gap-1.5 text-xs font-medium text-sky-400 hover:text-sky-300 transition disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            Advance Next Timeline Step
          </button>
          <button
            onClick={() => onAdvanceScenario('T0')}
            disabled={isAdvancing}
            className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-400 transition"
          >
            <RotateCcw className="w-3 h-3" />
            Reset to T0
          </button>
        </div>
      </div>
    </div>
  );
};

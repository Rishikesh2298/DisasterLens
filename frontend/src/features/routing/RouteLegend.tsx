import React from 'react';
import { RoadStatus } from '../../types/scene';

export const RouteLegend: React.FC = () => {
  const statusLegend: Array<{ status: RoadStatus; label: string; color: string; desc: string }> = [
    {
      status: 'CLEAR',
      label: 'No obstruction detected',
      color: '#22c55e',
      desc: 'Active observation confirms clear carriageway (age <= 3h).',
    },
    {
      status: 'BLOCKED',
      label: 'Blocked',
      color: '#ef4444',
      desc: 'Confirmed hazard intrusion blocking carriageway. Excluded from routing.',
    },
    {
      status: 'PARTIAL',
      label: 'Partial',
      color: '#f97316',
      desc: 'Partial obstruction detected. Traversable with penalty multiplier.',
    },
    {
      status: 'UNCERTAIN',
      label: 'Uncertain',
      color: '#a855f7',
      desc: 'Direct vs mapped conflict or incomplete recovery evidence. High penalty.',
    },
    {
      status: 'STALE',
      label: 'Stale (Aged Data)',
      color: '#eab308',
      desc: 'Prior observation exceeds freshness threshold. Highly penalized.',
    },
    {
      status: 'UNKNOWN',
      label: 'Unknown (No Sensor)',
      color: '#64748b',
      desc: 'No observation recorded. Evaluated with cautious baseline penalty.',
    },
  ];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl space-y-3">
      <h3 className="font-bold text-xs text-white uppercase tracking-wider">
        Road Condition Status & Freshness Legend
      </h3>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        {statusLegend.map(({ status, label, color, desc }) => (
          <div
            key={status}
            className="flex items-start gap-2.5 p-2 rounded-lg bg-slate-950/60 border border-slate-800/80"
          >
            <span
              className="w-3 h-3 rounded-full shrink-0 mt-0.5"
              style={{ backgroundColor: color }}
            />
            <div className="space-y-0.5">
              <div className="font-semibold text-xs text-slate-200">{label}</div>
              <div className="text-[10px] text-slate-400 leading-tight">{desc}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Route Line Styles */}
      <div className="pt-2 border-t border-slate-800 flex flex-wrap items-center gap-6 text-xs text-slate-400">
        <span className="font-medium text-slate-300">Route Map Styles:</span>
        <div className="flex items-center gap-2">
          <span className="w-5 h-1 bg-emerald-500 rounded" />
          <span className="text-slate-300">Recommended Route</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-0.5 border-b-2 border-dashed border-slate-400" />
          <span className="text-slate-300">Baseline Shortest (Dashed)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-5 h-1 bg-sky-400 rounded ring-1 ring-sky-400/50" />
          <span className="text-slate-300">Active Inspected Route</span>
        </div>
      </div>
    </div>
  );
};

import React, { useState } from 'react';
import {
  Building,
  Hazard,
  Intersection,
  RoadSegment,
  RoadStatus,
  SegmentState,
} from '../../types/scene';
import { Layers, ShieldCheck, Zap } from 'lucide-react';

export interface SceneCanvasProps {
  sceneImageUrl: string;
  segments: RoadSegment[];
  intersections?: Intersection[];
  buildings?: Building[];
  hazards: Hazard[];
  predictedHazards?: Hazard[];
  segmentStates: Record<string, SegmentState>;
  predictedStates?: Record<string, SegmentState>;
  selectedRoutePath?: string[];
  onNodeClick?: (nodeId: string) => void;
  onSegmentClick?: (segmentId: string) => void;
  className?: string;
}

const STATUS_COLORS: Record<RoadStatus, { stroke: string; fill: string; label: string; bg: string }> = {
  BLOCKED: {
    stroke: '#ef4444',
    fill: 'rgba(239, 68, 68, 0.45)',
    label: 'Blocked',
    bg: 'bg-red-500/20 text-red-300 border-red-500/40',
  },
  PARTIAL: {
    stroke: '#f97316',
    fill: 'rgba(249, 115, 22, 0.40)',
    label: 'Partial',
    bg: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  },
  CLEAR: {
    stroke: '#22c55e',
    fill: 'rgba(34, 197, 94, 0.35)',
    label: 'No obstruction detected',
    bg: 'bg-green-500/20 text-green-300 border-green-500/40',
  },
  UNCERTAIN: {
    stroke: '#a855f7',
    fill: 'rgba(168, 85, 247, 0.40)',
    label: 'Uncertain',
    bg: 'bg-purple-500/20 text-purple-300 border-purple-500/40',
  },
  STALE: {
    stroke: '#eab308',
    fill: 'rgba(234, 179, 8, 0.40)',
    label: 'Stale',
    bg: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
  },
  UNKNOWN: {
    stroke: '#64748b',
    fill: 'rgba(100, 116, 139, 0.30)',
    label: 'Unknown',
    bg: 'bg-slate-500/20 text-slate-300 border-slate-500/40',
  },
};

const HAZARD_FILLS: Record<string, string> = {
  flood: 'rgba(59, 130, 246, 0.55)',
  debris: 'rgba(180, 83, 9, 0.60)',
  fallen_tree: 'rgba(22, 101, 52, 0.70)',
  road_damage: 'rgba(30, 41, 59, 0.85)',
  damaged_building: 'rgba(220, 38, 38, 0.60)',
};

export const SceneCanvas: React.FC<SceneCanvasProps> = ({
  sceneImageUrl,
  segments,
  intersections = [],
  buildings = [],
  hazards,
  predictedHazards,
  segmentStates,
  predictedStates,
  selectedRoutePath = [],
  onNodeClick,
  onSegmentClick,
  className = '',
}) => {
  // Layer toggles
  const [showRoads, setShowRoads] = useState(true);
  const [showHazards, setShowHazards] = useState(true);
  const [showBuildings, setShowBuildings] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [viewMode, setViewMode] = useState<'ground_truth' | 'prediction'>('ground_truth');

  // Tooltip & hover state
  const [hoveredSegment, setHoveredSegment] = useState<RoadSegment | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);

  // Active states based on view mode
  const activeStates = viewMode === 'prediction' && predictedStates ? predictedStates : segmentStates;
  const activeHazards = viewMode === 'prediction' && predictedHazards ? predictedHazards : hazards;

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setMousePos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };

  return (
    <div className={`flex flex-col bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl ${className}`}>
      {/* Control bar / Toggles */}
      <div className="bg-slate-800/90 border-b border-slate-700/60 px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-sm">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-sky-400" />
          <span className="font-semibold text-slate-200">Scene Overlays</span>
        </div>

        {/* Layer checkboxes */}
        <div className="flex items-center gap-4 text-xs">
          <label className="flex items-center gap-1.5 cursor-pointer text-slate-300 hover:text-white transition">
            <input
              type="checkbox"
              checked={showRoads}
              onChange={(e) => setShowRoads(e.target.checked)}
              className="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-0"
            />
            Roads
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer text-slate-300 hover:text-white transition">
            <input
              type="checkbox"
              checked={showHazards}
              onChange={(e) => setShowHazards(e.target.checked)}
              className="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-0"
            />
            Hazards
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer text-slate-300 hover:text-white transition">
            <input
              type="checkbox"
              checked={showBuildings}
              onChange={(e) => setShowBuildings(e.target.checked)}
              className="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-0"
            />
            Buildings
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer text-slate-300 hover:text-white transition">
            <input
              type="checkbox"
              checked={showLabels}
              onChange={(e) => setShowLabels(e.target.checked)}
              className="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-0"
            />
            Labels
          </label>
        </div>

        {/* View Mode Toggle: Ground Truth vs Prediction */}
        <div className="flex items-center bg-slate-900/80 p-0.5 rounded-lg border border-slate-700">
          <button
            onClick={() => setViewMode('ground_truth')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition ${
              viewMode === 'ground_truth'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            Ground Truth
          </button>
          <button
            onClick={() => setViewMode('prediction')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition ${
              viewMode === 'prediction'
                ? 'bg-purple-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Zap className="w-3.5 h-3.5" />
            AI Prediction
          </button>
        </div>
      </div>

      {/* Canvas Viewport */}
      <div className="relative aspect-square w-full bg-slate-950 flex items-center justify-center overflow-hidden">
        {/* Base Scene Image */}
        {sceneImageUrl ? (
          <img
            src={sceneImageUrl}
            alt="Disaster Scene"
            className="absolute inset-0 w-full h-full object-contain pointer-events-none select-none"
          />
        ) : (
          <div className="text-slate-500 text-sm">No scene image loaded</div>
        )}

        {/* Interactive SVG Overlay */}
        <svg
          viewBox="0 0 1024 1024"
          className="absolute inset-0 w-full h-full cursor-crosshair"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => {
            setHoveredSegment(null);
            setMousePos(null);
          }}
        >
          {/* Buildings Layer */}
          {showBuildings &&
            buildings.map((bldg) => {
              const pointsStr = bldg.polygon.map((p) => `${p.x},${p.y}`).join(' ');
              return (
                <polygon
                  key={bldg.id}
                  points={pointsStr}
                  fill="rgba(148, 163, 184, 0.15)"
                  stroke="rgba(148, 163, 184, 0.35)"
                  strokeWidth="1.5"
                  className="pointer-events-none"
                />
              );
            })}

          {/* Road Segments Layer */}
          {showRoads &&
            segments.map((seg) => {
              const pointsStr = seg.polygon.map((p) => `${p.x},${p.y}`).join(' ');
              const state = activeStates[seg.id];
              const status: RoadStatus = state?.status || 'UNKNOWN';
              const conf = STATUS_COLORS[status] || STATUS_COLORS.UNKNOWN;
              const isSelected = selectedRoutePath.includes(seg.id);
              const isHovered = hoveredSegment?.id === seg.id;

              return (
                <g key={seg.id} className="cursor-pointer">
                  {/* Road Polygon */}
                  <polygon
                    points={pointsStr}
                    fill={isSelected ? 'rgba(56, 189, 248, 0.6)' : conf.fill}
                    stroke={isSelected ? '#38bdf8' : isHovered ? '#ffffff' : conf.stroke}
                    strokeWidth={isSelected ? '3.5' : isHovered ? '3' : '1.5'}
                    strokeDasharray={isSelected ? '6,3' : undefined}
                    onMouseEnter={() => setHoveredSegment(seg)}
                    onClick={() => onSegmentClick?.(seg.id)}
                    className="transition-colors duration-150"
                  />
                  {/* Segment Centerline Indicator */}
                  {seg.centerline.length >= 2 && (
                    <line
                      x1={seg.centerline[0].x}
                      y1={seg.centerline[0].y}
                      x2={seg.centerline[1].x}
                      y2={seg.centerline[1].y}
                      stroke={conf.stroke}
                      strokeWidth="1"
                      strokeOpacity="0.7"
                      className="pointer-events-none"
                    />
                  )}
                </g>
              );
            })}

          {/* Hazards Layer */}
          {showHazards &&
            activeHazards.map((h) => {
              const pointsStr = h.polygon.map((p) => `${p.x},${p.y}`).join(' ');
              const fill = HAZARD_FILLS[h.type] || 'rgba(239, 68, 68, 0.5)';
              return (
                <polygon
                  key={h.id}
                  points={pointsStr}
                  fill={fill}
                  stroke="#ffffff"
                  strokeWidth="1.5"
                  strokeOpacity="0.8"
                  className="pointer-events-none"
                />
              );
            })}

          {/* Road Labels Layer */}
          {showLabels &&
            segments.map((seg) => {
              if (seg.centerline.length < 2) return null;
              const mx = (seg.centerline[0].x + seg.centerline[1].x) / 2;
              const my = (seg.centerline[0].y + seg.centerline[1].y) / 2;
              return (
                <g key={`lbl-${seg.id}`} className="pointer-events-none select-none">
                  <rect
                    x={mx - 22}
                    y={my - 8}
                    width="44"
                    height="16"
                    rx="3"
                    fill="rgba(15, 23, 42, 0.85)"
                    stroke="rgba(255, 255, 255, 0.3)"
                    strokeWidth="0.8"
                  />
                  <text
                    x={mx}
                    y={my + 3.5}
                    textAnchor="middle"
                    fill="#f8fafc"
                    fontSize="9.5"
                    fontFamily="monospace"
                    fontWeight="600"
                  >
                    {seg.id}
                  </text>
                </g>
              );
            })}

          {/* Intersections (Nodes) */}
          {intersections.map((node) => {
            const isNodeSelected = selectedRoutePath.includes(node.id);
            return (
              <circle
                key={node.id}
                cx={node.x}
                cy={node.y}
                r={isNodeSelected ? '9' : '6'}
                fill={isNodeSelected ? '#38bdf8' : '#cbd5e1'}
                stroke="#0f172a"
                strokeWidth="2"
                onClick={() => onNodeClick?.(node.id)}
                className="cursor-pointer hover:scale-125 transition-transform"
              />
            );
          })}
        </svg>

        {/* Hover Tooltip */}
        {hoveredSegment && mousePos && (
          <div
            className="absolute pointer-events-none z-30 bg-slate-900/95 border border-slate-700/80 rounded-lg p-3 shadow-2xl text-xs space-y-1.5 backdrop-blur-md max-w-xs"
            style={{
              left: Math.min(mousePos.x + 12, 750),
              top: Math.min(mousePos.y + 12, 850),
            }}
          >
            <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-1.5">
              <span className="font-mono font-bold text-sky-400 text-sm">
                {hoveredSegment.id}
              </span>
              <span className="text-slate-400 text-[10px]">
                Zone {hoveredSegment.zone} • {hoveredSegment.length_m}m
              </span>
            </div>

            {/* Status with Safety-Compliant Wording */}
            {(() => {
              const state = activeStates[hoveredSegment.id];
              const status = state?.status || 'UNKNOWN';
              const conf = STATUS_COLORS[status];
              return (
                <div className="space-y-1 pt-0.5">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Status:</span>
                    <span
                      className={`px-2 py-0.5 rounded border text-[11px] font-semibold ${conf.bg}`}
                    >
                      {conf.label}
                    </span>
                  </div>

                  {state?.max_coverage !== undefined && (
                    <div className="flex items-center justify-between text-slate-300">
                      <span>Max Cross-Section:</span>
                      <span className="font-mono">
                        {(state.max_coverage * 100).toFixed(1)}%
                      </span>
                    </div>
                  )}

                  {state?.source && (
                    <div className="flex items-center justify-between text-slate-400 text-[10px]">
                      <span>Source:</span>
                      <span>{state.source}</span>
                    </div>
                  )}

                  {state?.captured_at && (
                    <div className="flex items-center justify-between text-slate-400 text-[10px]">
                      <span>Captured:</span>
                      <span>{new Date(state.captured_at).toLocaleTimeString()}</span>
                    </div>
                  )}

                  {state?.confidence !== undefined && (
                    <div className="flex items-center justify-between text-slate-400 text-[10px]">
                      <span>AI Confidence:</span>
                      <span>{(state.confidence * 100).toFixed(0)}%</span>
                    </div>
                  )}
                </div>
              );
            })()}

            <div className="border-t border-slate-800/80 pt-1 text-[9px] text-amber-400/80 italic">
              Synthetic benchmark data — not for actual navigation.
            </div>
          </div>
        )}
      </div>

      {/* Legend footer */}
      <div className="bg-slate-800/80 border-t border-slate-700/60 px-4 py-2 flex flex-wrap items-center justify-between gap-4 text-xs">
        <div className="flex items-center gap-3">
          <span className="text-slate-400 font-medium">Road Legend:</span>
          {(['BLOCKED', 'PARTIAL', 'CLEAR', 'UNCERTAIN', 'STALE', 'UNKNOWN'] as RoadStatus[]).map((st) => (
            <div key={st} className="flex items-center gap-1.5">
              <span
                className="w-2.5 h-2.5 rounded-full inline-block"
                style={{ backgroundColor: STATUS_COLORS[st].stroke }}
              />
              <span className="text-slate-300 text-[11px]">{STATUS_COLORS[st].label}</span>
            </div>
          ))}
        </div>
        <div className="text-slate-500 text-[11px]">
          Click segment or node to interact
        </div>
      </div>
    </div>
  );
};
export default SceneCanvas;

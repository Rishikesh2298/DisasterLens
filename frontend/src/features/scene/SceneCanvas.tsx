import React, { useState } from "react";
import {
  Building,
  Hazard,
  Intersection,
  RoadSegment,
  RoadStatus,
  SegmentState,
} from "../../types/scene";
import { Layers, ShieldCheck, Zap } from "lucide-react";

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
  baselineRoutePath?: string[];
  recommendedRoutePath?: string[];
  originNode?: string;
  destNode?: string;
  onNodeClick?: (nodeId: string) => void;
  onSegmentClick?: (segmentId: string) => void;
  className?: string;
}

const STATUS_COLORS: Record<
  RoadStatus,
  { stroke: string; fill: string; label: string; bg: string }
> = {
  BLOCKED: {
    stroke: "#ef4444",
    fill: "rgba(239, 68, 68, 0.45)",
    label: "Blocked",
    bg: "bg-red-500/20 text-red-300 border-red-500/40",
  },
  PARTIAL: {
    stroke: "#f97316",
    fill: "rgba(249, 115, 22, 0.40)",
    label: "Partial",
    bg: "bg-orange-500/20 text-orange-300 border-orange-500/40",
  },
  CLEAR: {
    stroke: "#22c55e",
    fill: "rgba(34, 197, 94, 0.35)",
    label: "No obstruction detected",
    bg: "bg-green-500/20 text-green-300 border-green-500/40",
  },
  UNCERTAIN: {
    stroke: "#a855f7",
    fill: "rgba(168, 85, 247, 0.40)",
    label: "Uncertain",
    bg: "bg-purple-500/20 text-purple-300 border-purple-500/40",
  },
  STALE: {
    stroke: "#eab308",
    fill: "rgba(234, 179, 8, 0.40)",
    label: "Stale",
    bg: "bg-yellow-500/20 text-yellow-300 border-yellow-500/40",
  },
  UNKNOWN: {
    stroke: "#64748b",
    fill: "rgba(100, 116, 139, 0.30)",
    label: "Unknown",
    bg: "bg-slate-500/20 text-slate-300 border-slate-500/40",
  },
};

const HAZARD_FILLS: Record<string, string> = {
  flood: "rgba(59, 130, 246, 0.65)",
  debris: "rgba(180, 83, 9, 0.70)",
  fallen_tree: "rgba(22, 101, 52, 0.75)",
  road_damage: "rgba(30, 41, 59, 0.85)",
  damaged_building: "rgba(220, 38, 38, 0.70)",
};

// Robust point parser supporting both {x, y} and [x, y]
const parsePoint = (p: any): { x: number; y: number } => {
  if (Array.isArray(p)) return { x: Number(p[0]) || 0, y: Number(p[1]) || 0 };
  if (p && typeof p === "object")
    return { x: Number(p.x) || 0, y: Number(p.y) || 0 };
  return { x: 0, y: 0 };
};

const parsePoints = (pts: any[]): Array<{ x: number; y: number }> => {
  if (!Array.isArray(pts)) return [];
  return pts.map(parsePoint);
};

const toSvgPoints = (pts: any[]): string => {
  return parsePoints(pts)
    .map((p) => `${p.x},${p.y}`)
    .join(" ");
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
  baselineRoutePath = [],
  recommendedRoutePath = [],
  originNode,
  destNode,
  onNodeClick,
  onSegmentClick,
  className = "",
}) => {
  // Layer toggles
  const [showRoads, setShowRoads] = useState(true);
  const [showHazards, setShowHazards] = useState(true);
  const [showBuildings, setShowBuildings] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [viewMode, setViewMode] = useState<"ground_truth" | "prediction">(
    "ground_truth",
  );

  // Image load error fallback state
  const [imageError, setImageError] = useState(false);

  // Tooltip & hover state
  const [hoveredSegment, setHoveredSegment] = useState<RoadSegment | null>(
    null,
  );
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(
    null,
  );

  // Active states based on view mode
  const activeStates =
    viewMode === "prediction" && predictedStates
      ? predictedStates
      : segmentStates;
  const activeHazards =
    viewMode === "prediction" && predictedHazards ? predictedHazards : hazards;

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setMousePos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };

  return (
    <div
      className={`flex flex-col bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl ${className}`}
    >
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
            onClick={() => setViewMode("ground_truth")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition ${
              viewMode === "ground_truth"
                ? "bg-sky-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            Ground Truth
          </button>
          <button
            onClick={() => setViewMode("prediction")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition ${
              viewMode === "prediction"
                ? "bg-purple-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Zap className="w-3.5 h-3.5" />
            AI Prediction
          </button>
        </div>
      </div>

      {/* Canvas Viewport */}
      <div className="relative aspect-square w-full bg-slate-950 flex items-center justify-center overflow-hidden">
        {/* Base Scene Image with Graceful Error Fallback */}
        {sceneImageUrl && !imageError ? (
          <img
            src={sceneImageUrl}
            alt="Disaster Scene"
            onError={() => setImageError(true)}
            className="absolute inset-0 w-full h-full object-contain pointer-events-none select-none"
          />
        ) : (
          <div className="absolute inset-0 w-full h-full bg-slate-950 flex flex-col items-center justify-center select-none pointer-events-none">
            {/* Subtle Cartographic Grid Pattern */}
            <div className="absolute inset-0 bg-[radial-gradient(#334155_1px,transparent_1px)] [background-size:32px_32px] opacity-40" />
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:128px_128px] opacity-25" />
          </div>
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
              const pointsStr = toSvgPoints(bldg.polygon);
              if (!pointsStr) return null;
              return (
                <polygon
                  key={bldg.id}
                  points={pointsStr}
                  fill="rgba(148, 163, 184, 0.18)"
                  stroke="rgba(148, 163, 184, 0.40)"
                  strokeWidth="1.5"
                  className="pointer-events-none"
                />
              );
            })}

          {/* Road Segments Layer */}
          {showRoads &&
            segments.map((seg) => {
              const pointsStr = toSvgPoints(seg.polygon);
              if (!pointsStr) return null;

              const state = activeStates[seg.id];
              const status: RoadStatus = state?.status || "UNKNOWN";
              const conf = STATUS_COLORS[status] || STATUS_COLORS.UNKNOWN;
              const isSelected = selectedRoutePath.includes(seg.id);
              const isRecommended = recommendedRoutePath.includes(seg.id);
              const isBaseline = baselineRoutePath.includes(seg.id);
              const isHovered = hoveredSegment?.id === seg.id;

              let fill = conf.fill;
              let stroke = isHovered ? "#ffffff" : conf.stroke;
              let strokeWidth = isHovered ? "3" : "1.5";
              let strokeDasharray: string | undefined = undefined;

              if (isSelected) {
                fill = "rgba(56, 189, 248, 0.65)";
                stroke = "#38bdf8";
                strokeWidth = "3.5";
                strokeDasharray = "6,3";
              } else if (isRecommended) {
                fill = "rgba(16, 185, 129, 0.55)";
                stroke = "#10b981";
                strokeWidth = "3";
              } else if (isBaseline) {
                fill = "rgba(148, 163, 184, 0.35)";
                stroke = "#94a3b8";
                strokeWidth = "2";
                strokeDasharray = "4,4";
              }

              const cl = parsePoints(seg.centerline);

              return (
                <g key={seg.id} className="cursor-pointer">
                  {/* Road Polygon */}
                  <polygon
                    points={pointsStr}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    strokeDasharray={strokeDasharray}
                    onMouseEnter={() => setHoveredSegment(seg)}
                    onClick={() => onSegmentClick?.(seg.id)}
                    className="transition-colors duration-150"
                  />
                  {/* Segment Centerline Indicator */}
                  {cl.length >= 2 && (
                    <line
                      x1={cl[0].x}
                      y1={cl[0].y}
                      x2={cl[1].x}
                      y2={cl[1].y}
                      stroke={conf.stroke}
                      strokeWidth="1.2"
                      strokeOpacity="0.75"
                      className="pointer-events-none"
                    />
                  )}
                </g>
              );
            })}

          {/* Dedicated Route Path Corridor Traces */}
          {showRoads && (
            <g className="pointer-events-none">
              {/* Baseline Path Trace (Amber dashed line) */}
              {baselineRoutePath.map((segId) => {
                const seg = segments.find((s) => s.id === segId);
                if (!seg) return null;
                const cl = parsePoints(seg.centerline);
                if (cl.length < 2) return null;
                return (
                  <line
                    key={`base-trace-${segId}`}
                    x1={cl[0].x}
                    y1={cl[0].y}
                    x2={cl[1].x}
                    y2={cl[1].y}
                    stroke="#f59e0b"
                    strokeWidth="3"
                    strokeDasharray="6,4"
                    strokeOpacity="0.8"
                  />
                );
              })}

              {/* Recommended Route Trace (Glowing emerald green solid line) */}
              {recommendedRoutePath.map((segId) => {
                const seg = segments.find((s) => s.id === segId);
                if (!seg) return null;
                const cl = parsePoints(seg.centerline);
                if (cl.length < 2) return null;
                return (
                  <line
                    key={`rec-trace-${segId}`}
                    x1={cl[0].x}
                    y1={cl[0].y}
                    x2={cl[1].x}
                    y2={cl[1].y}
                    stroke="#10b981"
                    strokeWidth="4.5"
                    strokeOpacity="0.9"
                  />
                );
              })}

              {/* Selected Inspection Route Trace (Sky blue dashed line) */}
              {selectedRoutePath.map((segId) => {
                const seg = segments.find((s) => s.id === segId);
                if (!seg) return null;
                const cl = parsePoints(seg.centerline);
                if (cl.length < 2) return null;
                return (
                  <line
                    key={`sel-trace-${segId}`}
                    x1={cl[0].x}
                    y1={cl[0].y}
                    x2={cl[1].x}
                    y2={cl[1].y}
                    stroke="#38bdf8"
                    strokeWidth="5"
                    strokeDasharray="8,4"
                    strokeOpacity="0.95"
                  />
                );
              })}
            </g>
          )}

          {/* Hazards Layer */}
          {showHazards &&
            activeHazards.map((h) => {
              const pointsStr = toSvgPoints(h.polygon);
              if (!pointsStr) return null;
              const fill = HAZARD_FILLS[h.type] || "rgba(239, 68, 68, 0.6)";
              return (
                <polygon
                  key={h.id}
                  points={pointsStr}
                  fill={fill}
                  stroke="#ffffff"
                  strokeWidth="1.8"
                  strokeOpacity="0.9"
                  className="pointer-events-none"
                />
              );
            })}

          {/* Road Segment Labels Layer */}
          {showLabels &&
            segments.map((seg) => {
              const cl = parsePoints(seg.centerline);
              if (cl.length < 2) return null;
              const mx = (cl[0].x + cl[1].x) / 2;
              const my = (cl[0].y + cl[1].y) / 2;
              return (
                <g
                  key={`lbl-${seg.id}`}
                  className="pointer-events-none select-none"
                >
                  <rect
                    x={mx - 22}
                    y={my - 8}
                    width="44"
                    height="16"
                    rx="3"
                    fill="rgba(15, 23, 42, 0.88)"
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
            const isOrigin = originNode === node.id;
            const isDest = destNode === node.id;
            const isSelected = selectedRoutePath.includes(node.id);

            let nodeFill = "#cbd5e1";
            let nodeStroke = "#0f172a";
            let radius = 6;

            if (isOrigin) {
              nodeFill = "#22c55e";
              nodeStroke = "#ffffff";
              radius = 9;
            } else if (isDest) {
              nodeFill = "#ef4444";
              nodeStroke = "#ffffff";
              radius = 9;
            } else if (isSelected) {
              nodeFill = "#38bdf8";
              radius = 8;
            }

            return (
              <g key={node.id} className="cursor-pointer">
                {/* Outer Ring for Origin/Destination */}
                {(isOrigin || isDest) && (
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={radius + 4}
                    fill="none"
                    stroke={isOrigin ? "#22c55e" : "#ef4444"}
                    strokeWidth="2"
                    strokeDasharray="4,2"
                    className="animate-spin origin-center"
                  />
                )}
                {/* Node Circle */}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius}
                  fill={nodeFill}
                  stroke={nodeStroke}
                  strokeWidth="2"
                  onClick={() => onNodeClick?.(node.id)}
                  className="hover:scale-125 transition-transform"
                />
                {/* Node Label / Origin / Destination Badges */}
                {(showLabels || isOrigin || isDest) && (
                  <g className="pointer-events-none select-none">
                    <rect
                      x={node.x - 14}
                      y={node.y - (isOrigin || isDest ? 24 : 18)}
                      width={isOrigin || isDest ? 36 : 28}
                      height="13"
                      rx="2.5"
                      fill={
                        isOrigin
                          ? "#15803d"
                          : isDest
                            ? "#b91c1c"
                            : "rgba(15, 23, 42, 0.9)"
                      }
                      stroke={
                        isOrigin
                          ? "#86efac"
                          : isDest
                            ? "#fca5a5"
                            : "rgba(255, 255, 255, 0.25)"
                      }
                      strokeWidth="0.7"
                    />
                    <text
                      x={node.x + (isOrigin || isDest ? 4 : 0)}
                      y={node.y - (isOrigin || isDest ? 14.5 : 9)}
                      textAnchor="middle"
                      fill="#ffffff"
                      fontSize={isOrigin || isDest ? "8" : "8.5"}
                      fontFamily="monospace"
                      fontWeight="bold"
                    >
                      {isOrigin ? "ORIGIN" : isDest ? "DEST" : node.id}
                    </text>
                  </g>
                )}
              </g>
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
              const status = state?.status || "UNKNOWN";
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
                      <span>
                        {new Date(state.captured_at).toLocaleTimeString()}
                      </span>
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
          {(
            [
              "BLOCKED",
              "PARTIAL",
              "CLEAR",
              "UNCERTAIN",
              "STALE",
              "UNKNOWN",
            ] as RoadStatus[]
          ).map((st) => (
            <div key={st} className="flex items-center gap-1.5">
              <span
                className="w-2.5 h-2.5 rounded-full inline-block"
                style={{ backgroundColor: STATUS_COLORS[st].stroke }}
              />
              <span className="text-slate-300 text-[11px]">
                {STATUS_COLORS[st].label}
              </span>
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

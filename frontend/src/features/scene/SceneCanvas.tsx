import React, { useEffect, useState } from "react";
import {
  Building,
  Hazard,
  Intersection,
  NormalizedRoadStatus,
  RoadSegment,
  SegmentState,
  normalizeStatus,
} from "../../types/scene";
import "./scene.css";

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
  imageWidth?: number;
  imageHeight?: number;
  className?: string;
}

const STATUS_META: Record<
  NormalizedRoadStatus,
  {
    stroke: string;
    fill: string;
    label: string;
    pillBg: string;
    pillFg: string;
  }
> = {
  BLOCKED: {
    stroke: "#ef4444",
    fill: "rgba(239, 68, 68, 0.45)",
    label: "Blocked",
    pillBg: "rgba(239, 68, 68, 0.2)",
    pillFg: "#fca5a5",
  },
  PARTIAL: {
    stroke: "#f97316",
    fill: "rgba(249, 115, 22, 0.40)",
    label: "Partial",
    pillBg: "rgba(249, 115, 22, 0.2)",
    pillFg: "#fdba74",
  },
  CLEAR: {
    stroke: "#22c55e",
    fill: "rgba(34, 197, 94, 0.35)",
    label: "No obstruction detected",
    pillBg: "rgba(34, 197, 94, 0.2)",
    pillFg: "#86efac",
  },
  UNCERTAIN: {
    stroke: "#a855f7",
    fill: "rgba(168, 85, 247, 0.40)",
    label: "Uncertain",
    pillBg: "rgba(168, 85, 247, 0.2)",
    pillFg: "#d8b4fe",
  },
  STALE: {
    stroke: "#eab308",
    fill: "rgba(234, 179, 8, 0.38)",
    label: "Stale",
    pillBg: "rgba(234, 179, 8, 0.2)",
    pillFg: "#fde047",
  },
  UNKNOWN: {
    stroke: "#94a3b8",
    fill: "rgba(148, 163, 184, 0.30)",
    label: "Unknown",
    pillBg: "rgba(148, 163, 184, 0.2)",
    pillFg: "#cbd5e1",
  },
};

const HAZARD_FILLS: Record<string, string> = {
  flood: "rgba(59, 130, 246, 0.55)",
  debris: "rgba(180, 83, 9, 0.60)",
  fallen_tree: "rgba(22, 101, 52, 0.70)",
  road_damage: "rgba(30, 41, 59, 0.85)",
  damaged_building: "rgba(220, 38, 38, 0.60)",
};

const parsePoint = (p: unknown): { x: number; y: number } => {
  if (Array.isArray(p)) return { x: Number(p[0]) || 0, y: Number(p[1]) || 0 };
  if (p && typeof p === "object") {
    const obj = p as { x?: unknown; y?: unknown };
    return { x: Number(obj.x) || 0, y: Number(obj.y) || 0 };
  }
  return { x: 0, y: 0 };
};

const parsePoints = (pts: unknown[]): Array<{ x: number; y: number }> => {
  if (!Array.isArray(pts)) return [];
  return pts.map(parsePoint);
};

const toSvgPoints = (pts: unknown[]): string => {
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
  imageWidth = 1024,
  imageHeight = 1024,
  className = "",
}) => {
  const [showRoads, setShowRoads] = useState(true);
  const [showHazards, setShowHazards] = useState(true);
  const [showBuildings, setShowBuildings] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [viewMode, setViewMode] = useState<"ground_truth" | "prediction">(
    "ground_truth",
  );
  const [imageStatus, setImageStatus] = useState<"loading" | "ready" | "error">(
    sceneImageUrl ? "loading" : "error",
  );

  useEffect(() => {
    setImageStatus(sceneImageUrl ? "loading" : "error");
  }, [sceneImageUrl]);

  const [hoveredSegment, setHoveredSegment] = useState<RoadSegment | null>(
    null,
  );
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(
    null,
  );

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
    <div className={`dl-scene-card ${className}`}>
      <div className="dl-scene-toolbar">
        <div className="dl-toolbar-title">
          <span>Scene Overlays</span>
        </div>

        <div
          className="dl-toggle-group"
          role="group"
          aria-label="Layer toggles"
        >
          <label className="dl-toggle-label">
            <input
              type="checkbox"
              checked={showRoads}
              onChange={(e) => setShowRoads(e.target.checked)}
            />
            Roads
          </label>
          <label className="dl-toggle-label">
            <input
              type="checkbox"
              checked={showHazards}
              onChange={(e) => setShowHazards(e.target.checked)}
            />
            Hazards
          </label>
          <label className="dl-toggle-label">
            <input
              type="checkbox"
              checked={showBuildings}
              onChange={(e) => setShowBuildings(e.target.checked)}
            />
            Buildings
          </label>
          <label className="dl-toggle-label">
            <input
              type="checkbox"
              checked={showLabels}
              onChange={(e) => setShowLabels(e.target.checked)}
            />
            Labels
          </label>
        </div>

        <div
          className="dl-mode-switch"
          role="group"
          aria-label="Ground truth versus prediction"
        >
          <button
            type="button"
            onClick={() => setViewMode("ground_truth")}
            className={`dl-mode-btn ${viewMode === "ground_truth" ? "active" : ""}`}
          >
            Ground Truth
          </button>
          <button
            type="button"
            onClick={() => setViewMode("prediction")}
            className={`dl-mode-btn ${viewMode === "prediction" ? "active-pred" : ""}`}
          >
            AI Prediction
          </button>
        </div>
      </div>

      <div className="dl-canvas-viewport">
        {sceneImageUrl && imageStatus !== "error" ? (
          <img
            key={sceneImageUrl}
            src={sceneImageUrl}
            alt="Synthetic disaster scene"
            className="dl-canvas-img"
            onLoad={() => setImageStatus("ready")}
            onError={() => setImageStatus("error")}
          />
        ) : null}

        {!sceneImageUrl && (
          <div className="dl-canvas-empty">No scene image selected.</div>
        )}
        {sceneImageUrl && imageStatus === "loading" && (
          <div className="dl-canvas-empty">Loading scene imagery…</div>
        )}

        <svg
          viewBox={`0 0 ${imageWidth} ${imageHeight}`}
          className="dl-canvas-svg"
          aria-label="Interactive scene geometry overlay"
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
                  stroke="rgba(148, 163, 184, 0.45)"
                  strokeWidth="1.5"
                  pointerEvents="none"
                />
              );
            })}

          {/* Road Segments Layer */}
          {showRoads &&
            segments.map((seg) => {
              const pointsStr = toSvgPoints(seg.polygon);
              if (!pointsStr) return null;
              const state = activeStates[seg.id];
              const status = normalizeStatus(state?.status);
              const meta = STATUS_META[status];
              const isSelected = selectedRoutePath.includes(seg.id);
              const isRecommended = recommendedRoutePath.includes(seg.id);
              const isBaseline = baselineRoutePath.includes(seg.id);
              const isHovered = hoveredSegment?.id === seg.id;

              let fill = meta.fill;
              let stroke = isHovered ? "#ffffff" : meta.stroke;
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
                <g key={seg.id} style={{ cursor: "pointer" }}>
                  <polygon
                    points={pointsStr}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    strokeDasharray={strokeDasharray}
                    onMouseEnter={() => setHoveredSegment(seg)}
                    onClick={() => onSegmentClick?.(seg.id)}
                  />
                  {cl.length >= 2 && (
                    <line
                      x1={cl[0].x}
                      y1={cl[0].y}
                      x2={cl[1].x}
                      y2={cl[1].y}
                      stroke={meta.stroke}
                      strokeWidth="1.2"
                      strokeOpacity="0.75"
                      pointerEvents="none"
                    />
                  )}
                </g>
              );
            })}

          {/* Dedicated Route Path Corridor Traces */}
          {showRoads && (
            <g pointerEvents="none">
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
              const fill = HAZARD_FILLS[h.type] || "rgba(239, 68, 68, 0.5)";
              const isPred = viewMode === "prediction";
              return (
                <polygon
                  key={h.id}
                  points={pointsStr}
                  fill={fill}
                  stroke={isPred ? "#c084fc" : "#ffffff"}
                  strokeWidth={isPred ? "2" : "1.5"}
                  strokeDasharray={isPred ? "5,3" : undefined}
                  strokeOpacity="0.85"
                  pointerEvents="none"
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
                  pointerEvents="none"
                  style={{ userSelect: "none" }}
                >
                  <rect
                    x={mx - 22}
                    y={my - 8}
                    width="44"
                    height="16"
                    rx="3"
                    fill="rgba(17, 26, 24, 0.86)"
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
            let nodeStroke = "#111a18";
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
              <g key={node.id} style={{ cursor: "pointer" }}>
                {(isOrigin || isDest) && (
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={radius + 4}
                    fill="none"
                    stroke={isOrigin ? "#22c55e" : "#ef4444"}
                    strokeWidth="2"
                    strokeDasharray="4,2"
                  />
                )}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius}
                  fill={nodeFill}
                  stroke={nodeStroke}
                  strokeWidth="2"
                  onClick={() => onNodeClick?.(node.id)}
                />
                {(showLabels || isOrigin || isDest) && (
                  <g pointerEvents="none" style={{ userSelect: "none" }}>
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
                            : "rgba(17, 26, 24, 0.9)"
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

        {hoveredSegment && mousePos && (
          <div
            className="dl-tooltip"
            style={{
              left: Math.max(8, Math.min(mousePos.x + 12, 340)),
              top: Math.max(8, Math.min(mousePos.y + 12, 380)),
            }}
          >
            <div className="dl-tooltip-head">
              <strong style={{ fontFamily: "monospace", color: "#86efac" }}>
                {hoveredSegment.id}
              </strong>
              <span style={{ fontSize: 10, color: "#a6b3ac" }}>
                Zone {hoveredSegment.zone} · {hoveredSegment.length_m}m
              </span>
            </div>

            {(() => {
              const state = activeStates[hoveredSegment.id];
              const status = normalizeStatus(state?.status);
              const meta = STATUS_META[status];
              return (
                <div>
                  <div className="dl-tooltip-row">
                    <span>Status:</span>
                    <span
                      className="dl-status-pill"
                      style={{ background: meta.pillBg, color: meta.pillFg }}
                    >
                      {meta.label}
                    </span>
                  </div>

                  {state?.max_coverage !== undefined && (
                    <div className="dl-tooltip-row">
                      <span>Max cross-section:</span>
                      <span style={{ fontFamily: "monospace" }}>
                        {(state.max_coverage * 100).toFixed(1)}%
                      </span>
                    </div>
                  )}

                  {state?.age_hours !== undefined && (
                    <div className="dl-tooltip-row">
                      <span>Observation age:</span>
                      <span style={{ fontFamily: "monospace" }}>
                        {state.age_hours.toFixed(1)}h
                      </span>
                    </div>
                  )}

                  {state?.source && (
                    <div className="dl-tooltip-row">
                      <span>Source:</span>
                      <span>{state.source}</span>
                    </div>
                  )}

                  {state?.captured_at && (
                    <div className="dl-tooltip-row">
                      <span>Captured:</span>
                      <span>{state.captured_at}</span>
                    </div>
                  )}

                  {state?.confidence !== undefined && (
                    <div className="dl-tooltip-row">
                      <span>AI Confidence:</span>
                      <span>{(state.confidence * 100).toFixed(0)}%</span>
                    </div>
                  )}
                </div>
              );
            })()}

            <div className="dl-tooltip-note">
              Synthetic scenes only — not real-world disaster performance.
            </div>
          </div>
        )}
      </div>

      <div className="dl-scene-legend">
        <div className="dl-legend-items">
          <strong>Legend:</strong>
          {(
            [
              "BLOCKED",
              "PARTIAL",
              "CLEAR",
              "UNCERTAIN",
              "STALE",
              "UNKNOWN",
            ] as NormalizedRoadStatus[]
          ).map((st) => (
            <span key={st} className="dl-legend-item">
              <span
                className="dl-legend-dot"
                style={{ backgroundColor: STATUS_META[st].stroke }}
              />
              <span>{STATUS_META[st].label}</span>
            </span>
          ))}
        </div>
        <span>
          Mode: {viewMode === "prediction" ? "AI Prediction" : "Ground Truth"}
        </span>
      </div>
    </div>
  );
};

export default SceneCanvas;

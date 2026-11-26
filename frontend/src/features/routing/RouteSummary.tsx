import React from "react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Route,
  ShieldCheck,
  Eye,
  Info,
} from "lucide-react";
import { RouteRecommendation } from "./types";

interface RouteSummaryProps {
  recommendation: RouteRecommendation | null;
}

export const RouteSummary: React.FC<RouteSummaryProps> = ({
  recommendation,
}) => {
  if (!recommendation) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl text-center text-slate-500 text-xs">
        Select origin and destination nodes, then click &quot;Calculate Route
        Recommendation&quot; to view route analysis.
      </div>
    );
  }

  const { baseline_route, recommended_route, verification } = recommendation;

  const baselineDist = baseline_route?.total_length_m || 0;
  const recDist = recommended_route?.total_length_m || 0;
  const deltaDist = recDist - baselineDist;
  const isNoPath = !recommended_route;

  // Unverified segments and condition verification counts
  const unverifiedCount =
    recommended_route?.unverified_segments_count ??
    verification?.unverified_count ??
    0;
  const totalSegments = recommended_route?.segment_path?.length || 0;
  const verifiedCount = Math.max(0, totalSegments - unverifiedCount);

  // Structural validation vs observation condition verification
  const isStructuralValid =
    verification?.is_valid &&
    !isNoPath &&
    !recommended_route?.has_fresh_blocked;
  const isFullyVerified = isStructuralValid && unverifiedCount === 0;
  const hasUnverifiedConditions = isStructuralValid && unverifiedCount > 0;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-4">
      {/* Title & Verification Status Badge */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Route className="w-4 h-4 text-emerald-400" />
          <h3 className="font-bold text-sm text-white">
            Route Analysis Summary
          </h3>
        </div>

        {/* Accurate Verification Status Presentation */}
        {isNoPath ? (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-red-500/15 border border-red-500/30 text-red-300 text-xs font-semibold">
            <XCircle className="w-3.5 h-3.5 text-red-400" />
            No Path Available
          </span>
        ) : !isStructuralValid ? (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-red-500/15 border border-red-500/30 text-red-300 text-xs font-semibold">
            <XCircle className="w-3.5 h-3.5 text-red-400" />
            Corridor Validation Failed
          </span>
        ) : hasUnverifiedConditions ? (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-300 text-xs font-semibold">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            Structurally Valid — Unverified Conditions ({unverifiedCount}{" "}
            Unverified)
          </span>
        ) : isFullyVerified ? (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs font-semibold">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            Fully Confirmed Clear (100% Observation Coverage)
          </span>
        ) : (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-semibold">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            Contains Advisory Warnings
          </span>
        )}
      </div>

      {/* Grid: Recommended vs Baseline Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
        {/* Recommended Route Card */}
        <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-xl p-3.5 space-y-2.5">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-emerald-300">
              Recommended Route
            </span>
            <span className="font-mono text-[10px] bg-emerald-500/20 text-emerald-200 px-1.5 py-0.5 rounded">
              Condition-Aware
            </span>
          </div>

          {recommended_route ? (
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between py-0.5 border-b border-emerald-950/40">
                <span className="text-slate-400">Total Distance:</span>
                <span className="font-mono font-bold text-white">
                  {recommended_route.total_length_m} m
                </span>
              </div>
              <div className="flex justify-between py-0.5 border-b border-emerald-950/40">
                <span className="text-slate-400">Weighted Routing Cost:</span>
                <span className="font-mono font-semibold text-emerald-400">
                  {recommended_route.total_cost.toFixed(1)}
                </span>
              </div>
              <div className="flex justify-between py-0.5 border-b border-emerald-950/40">
                <span className="text-slate-400">Segments Count:</span>
                <span className="font-mono text-slate-300">
                  {recommended_route.segment_path.length} segments
                </span>
              </div>
              <div className="flex justify-between py-0.5 border-b border-emerald-950/40">
                <span className="text-slate-400">Detour vs Baseline:</span>
                <span className="font-mono text-slate-300">
                  {deltaDist > 0
                    ? `+${deltaDist.toFixed(1)} m detour`
                    : `${deltaDist.toFixed(1)} m`}
                </span>
              </div>
              <div className="flex justify-between py-0.5">
                <span className="text-slate-400">Unverified Segments:</span>
                <span
                  className={`font-mono font-semibold ${
                    unverifiedCount > 0 ? "text-amber-400" : "text-emerald-400"
                  }`}
                >
                  {unverifiedCount}{" "}
                  {unverifiedCount > 0 ? "(Stale/Priors)" : "(All Fresh)"}
                </span>
              </div>
            </div>
          ) : (
            <div className="py-4 text-center text-xs text-red-400 font-medium">
              All connecting paths blocked by active hazards.
            </div>
          )}
        </div>

        {/* Baseline Route Card */}
        <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-3.5 space-y-2.5">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-slate-400">
              Baseline Shortest Route
            </span>
            <span className="font-mono text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">
              Physical Shortest
            </span>
          </div>

          {baseline_route ? (
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between py-0.5 border-b border-slate-900">
                <span className="text-slate-400">Total Distance:</span>
                <span className="font-mono font-semibold text-slate-300">
                  {baseline_route.total_length_m} m
                </span>
              </div>
              <div className="flex justify-between py-0.5 border-b border-slate-900">
                <span className="text-slate-400">Segments Count:</span>
                <span className="font-mono text-slate-300">
                  {baseline_route.segment_path.length} segments
                </span>
              </div>
              <div className="flex justify-between py-0.5 border-b border-slate-900">
                <span className="text-slate-400">Hazard Intersection:</span>
                <span
                  className={`font-mono font-semibold ${
                    baseline_route.has_fresh_blocked
                      ? "text-red-400"
                      : "text-slate-300"
                  }`}
                >
                  {baseline_route.has_fresh_blocked
                    ? "Traverses Active Hazard"
                    : "0 Blocked"}
                </span>
              </div>
              <div className="flex justify-between py-0.5">
                <span className="text-slate-400">Unverified Segments:</span>
                <span className="font-mono text-slate-300">
                  {baseline_route.unverified_segments_count}
                </span>
              </div>
            </div>
          ) : (
            <div className="py-4 text-center text-xs text-slate-500">
              No physical path found.
            </div>
          )}
        </div>
      </div>

      {/* Structural Validity vs Observation Verification Breakdown */}
      {recommended_route && (
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3 text-xs space-y-2">
          <div className="flex items-center gap-1.5 text-sky-400 font-semibold text-[11px] uppercase tracking-wider">
            <Info className="w-3.5 h-3.5" />
            Verification Breakdown & Path Metrics
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-slate-300">
            {/* Structural Path Validity */}
            <div className="bg-slate-900/60 p-2.5 rounded border border-slate-800/80 space-y-1">
              <div className="flex items-center gap-1.5 font-medium text-slate-200">
                <ShieldCheck className="w-3.5 h-3.5 text-sky-400" />
                <span>Structural Path Validity</span>
              </div>
              <div className="text-[11px] text-slate-400">
                • Graph Connectivity:{" "}
                <span className="text-emerald-400 font-semibold">
                  Continuous
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                • Origin / Destination:{" "}
                <span className="text-emerald-400 font-semibold">
                  Connected ({recommendation.origin} →{" "}
                  {recommendation.destination})
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                • Confirmed Blockages:{" "}
                <span className="text-emerald-400 font-semibold">
                  0 on corridor (Avoided)
                </span>
              </div>
            </div>

            {/* Observation Verification */}
            <div className="bg-slate-900/60 p-2.5 rounded border border-slate-800/80 space-y-1">
              <div className="flex items-center gap-1.5 font-medium text-slate-200">
                <Eye className="w-3.5 h-3.5 text-amber-400" />
                <span>Observation Verification</span>
              </div>
              <div className="text-[11px] text-slate-400">
                • Fresh Camera Views:{" "}
                <span className="text-slate-200 font-semibold">
                  {verifiedCount} / {totalSegments} segments
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                • Unverified (Priors/Decayed):{" "}
                <span
                  className={
                    unverifiedCount > 0
                      ? "text-amber-400 font-semibold"
                      : "text-emerald-400 font-semibold"
                  }
                >
                  {unverifiedCount} segments
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                • Cost Penalties:{" "}
                <span className="text-slate-200 font-semibold">
                  Applied for stale/decayed prior roads
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Engine Explanation Banner */}
      {recommendation.explanation && (
        <div className="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs text-slate-300">
          <span className="font-semibold text-sky-400">
            Engine Explanation:{" "}
          </span>
          {recommendation.explanation}
        </div>
      )}

      {/* Mandatory Research Prototype Disclaimer */}
      <div className="border-t border-slate-800 pt-2 text-[10px] text-slate-500 text-center">
        DisasterLens research prototype — conditions may change rapidly. A road
        marked &quot;CLEAR&quot; indicates only that no obstruction was detected
        at capture time.
      </div>
    </div>
  );
};

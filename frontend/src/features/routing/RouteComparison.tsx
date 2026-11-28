import React from "react";
import { RouteAlternative, RouteRecommendation } from "./types";
import { Check, ShieldAlert, Sparkles, Navigation } from "lucide-react";

interface RouteComparisonProps {
  recommendation: RouteRecommendation | null;
  activeRouteKey: string;
  onSelectRoute: (routeKey: string, route: RouteAlternative | null) => void;
}

export const RouteComparison: React.FC<RouteComparisonProps> = ({
  recommendation,
  activeRouteKey,
  onSelectRoute,
}) => {
  if (!recommendation) {
    return null;
  }

  const {
    baseline_route,
    recommended_route,
    alternatives = [],
  } = recommendation;

  const routesList: Array<{
    key: string;
    title: string;
    badge: string;
    badgeClass: string;
    route: RouteAlternative | null;
  }> = [
    {
      key: "recommended",
      title: "Recommended Route",
      badge: "Condition-Aware",
      badgeClass: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
      route: recommended_route,
    },
    {
      key: "baseline",
      title: "Baseline Route",
      badge: "Shortest Distance",
      badgeClass: "bg-slate-800 text-slate-300 border-slate-700",
      route: baseline_route,
    },
    ...alternatives.map((alt, idx) => ({
      key: `alt-${alt.rank || idx + 2}`,
      title: `Alternative Path ${alt.rank || idx + 2}`,
      badge: `Rank ${alt.rank || idx + 2}`,
      badgeClass: "bg-indigo-500/15 text-indigo-300 border-indigo-500/40",
      route: alt,
    })),
  ];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-sky-400" />
          <h3 className="font-bold text-sm text-white">
            Route Alternatives & Comparison
          </h3>
        </div>
        <span className="text-xs text-slate-400">
          Click any card to inspect path on map canvas
        </span>
      </div>

      {/* Responsive Grid: 2 readable cards per row with generous spacing */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {routesList.map(({ key, title, badge, badgeClass, route }) => {
          const isSelected = activeRouteKey === key;
          const isValid = route?.is_valid && !route?.has_fresh_blocked;

          return (
            <div
              key={key}
              onClick={() => onSelectRoute(key, route)}
              className={`p-4 rounded-xl border cursor-pointer transition-all flex flex-col justify-between ${
                isSelected
                  ? "bg-gradient-to-b from-sky-950/60 to-slate-900 border-sky-400 ring-2 ring-sky-500/40 shadow-xl"
                  : "bg-slate-950/60 border-slate-800 hover:border-slate-700 hover:bg-slate-800/40"
              }`}
            >
              <div>
                {/* Header: Badge & Selected Tag */}
                <div className="flex items-center justify-between mb-2.5">
                  <span
                    className={`text-[11px] font-mono font-medium px-2.5 py-0.5 rounded border ${badgeClass}`}
                  >
                    {badge}
                  </span>
                  {isSelected ? (
                    <span className="flex items-center gap-1 text-[11px] font-bold text-sky-400 bg-sky-500/10 border border-sky-500/20 px-2 py-0.5 rounded-full">
                      <Check className="w-3.5 h-3.5" />
                      Active Preview
                    </span>
                  ) : (
                    <span className="text-[10px] text-slate-500 hover:text-slate-400 flex items-center gap-1">
                      <Navigation className="w-3 h-3" />
                      Click to view
                    </span>
                  )}
                </div>

                {/* Title */}
                <h4 className="font-bold text-sm text-white mb-3">{title}</h4>

                {/* Key Metrics */}
                {route ? (
                  <div className="space-y-2 text-xs text-slate-300">
                    <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Distance:</span>
                      <span className="font-mono font-bold text-white text-sm">
                        {route.total_length_m} m
                      </span>
                    </div>

                    <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">
                        Weighted Routing Cost:
                      </span>
                      <span className="font-mono font-bold text-emerald-400">
                        {route.total_cost.toFixed(1)}
                      </span>
                    </div>

                    <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">
                        Segments Traversed:
                      </span>
                      <span className="font-mono text-slate-200">
                        {route.segment_path.length} segments
                      </span>
                    </div>

                    <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">
                        Unverified Segments:
                      </span>
                      <span
                        className={`font-mono font-semibold ${
                          route.unverified_segments_count > 0
                            ? "text-amber-400"
                            : "text-emerald-400"
                        }`}
                      >
                        {route.unverified_segments_count}
                      </span>
                    </div>

                    {/* Condition Status Badge */}
                    <div className="pt-2 flex items-center justify-between text-[11px]">
                      <span className="text-slate-400">Condition Check:</span>
                      {route.has_fresh_blocked ? (
                        <span className="flex items-center gap-1 text-red-400 font-bold">
                          <ShieldAlert className="w-3.5 h-3.5" />
                          Crosses Active Hazard
                        </span>
                      ) : isValid ? (
                        <span className="text-emerald-400 font-semibold flex items-center gap-1">
                          Passes Structural Check
                        </span>
                      ) : (
                        <span className="text-amber-400 font-semibold">
                          Contains Warnings
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-6 text-xs text-slate-500">
                    No route path generated.
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default RouteComparison;

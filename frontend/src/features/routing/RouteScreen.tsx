import React, { useState, useEffect, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { SceneCanvas } from "../scene/SceneCanvas";
import { RouteControls } from "./RouteControls";
import { RouteSummary } from "./RouteSummary";
import { RouteComparison } from "./RouteComparison";
import { RouteLegend } from "./RouteLegend";
import { RouteWarnings } from "./RouteWarnings";
import {
  useCity,
  useCitySegments,
  useScenario,
  useClock,
  useRecommendRoute,
  useAdvanceScenario,
} from "./hooks";
import { fetchClock } from "./api";
import { RouteAlternative, RouteRecommendation, RouteAlertItem } from "./types";
import { RoadSegment, SceneData } from "../../types/scene";
import { Navigation, RefreshCw } from "lucide-react";

export const RouteScreen: React.FC = () => {
  const cityId = "DEMO-001";
  const scenarioId = "demo_city";
  const queryClient = useQueryClient();
  const timelineSeqRef = useRef(0);

  // API Queries
  const { data: city, isLoading: isCityLoading } = useCity(cityId);
  const { data: clock } = useClock();
  const { data: segmentStates = {} } = useCitySegments(
    cityId,
    clock?.simulated_time,
  );
  const { data: scenario } = useScenario(scenarioId);

  // Authentic Scene Data (for buildings, ground-truth hazards, and geometries)
  const [sceneData, setSceneData] = useState<SceneData | null>(null);

  useEffect(() => {
    fetch("/scenarios/demo_city/scene.json")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setSceneData(data);
      })
      .catch(() => {});
  }, []);

  // Mutations
  const recommendMutation = useRecommendRoute();
  const advanceMutation = useAdvanceScenario();

  // Component state
  const [origin, setOrigin] = useState("N1");
  const [destination, setDestination] = useState("N36");
  const [recommendation, setRecommendation] =
    useState<RouteRecommendation | null>(null);
  const [activeRouteKey, setActiveRouteKey] = useState<string>("recommended");
  const [activeRoute, setActiveRoute] = useState<RouteAlternative | null>(null);
  const [latestAlerts, setLatestAlerts] = useState<RouteAlertItem[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Calculate route handler
  const handleCalculateRoute = useCallback(
    async (targetAsOf?: string | null) => {
      if (!origin || !destination) {
        setErrorMessage("Please select both origin and destination nodes.");
        return;
      }
      const currentSeq = ++timelineSeqRef.current;
      setErrorMessage(null);
      try {
        const effectiveAsOf =
          typeof targetAsOf === "string" || targetAsOf === null
            ? targetAsOf
            : clock?.simulated_time;
        const result = await recommendMutation.mutateAsync({
          city_id: cityId,
          origin,
          destination,
          as_of: effectiveAsOf,
          save_as: "ROUTE-ACTIVE-DISPLAY",
          route_name: `Active Display (${origin}->${destination})`,
        });
        if (currentSeq !== timelineSeqRef.current) return;
        setRecommendation(result);
        setActiveRouteKey("recommended");
        setActiveRoute(
          result.recommended_route || result.baseline_route || null,
        );
      } catch (err: any) {
        if (currentSeq !== timelineSeqRef.current) return;
        setErrorMessage(
          err.message || "Failed to calculate route recommendation.",
        );
      }
    },
    [origin, destination, cityId, clock?.simulated_time, recommendMutation],
  );

  // Initial calculation on load
  useEffect(() => {
    if (city && !recommendation && !recommendMutation.isPending) {
      handleCalculateRoute();
    }
  }, [city, recommendation, handleCalculateRoute, recommendMutation.isPending]);

  // Advance scenario handler
  const handleAdvanceScenario = async (targetStep?: string) => {
    const currentSeq = ++timelineSeqRef.current;
    try {
      setErrorMessage(null);
      const res = await advanceMutation.mutateAsync({
        scenarioId,
        timeStep: targetStep,
      });

      if (currentSeq !== timelineSeqRef.current) return;

      // Always synchronize corridor alerts (clears stale alerts if empty)
      setLatestAlerts(res.alerts || []);

      // Synchronously fetch and wait for updated clock response
      const updatedClock = await queryClient.fetchQuery({
        queryKey: ["clock"],
        queryFn: fetchClock,
      });

      if (currentSeq !== timelineSeqRef.current) return;

      // Optimistically update scenario step in cache for instant UI feedback
      queryClient.setQueryData(["scenario", scenarioId], (old: any) =>
        old
          ? {
              ...old,
              current_time_step: res.time_step,
              current_simulated_time: res.timestamp,
            }
          : old,
      );

      // Invalidate queries so segment state badges and scenario update
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["citySegments"] }),
        queryClient.invalidateQueries({ queryKey: ["scenario", scenarioId] }),
        queryClient.invalidateQueries({ queryKey: ["scenarios"] }),
      ]);

      if (currentSeq !== timelineSeqRef.current) return;

      // Explicitly recalculate route with the verified clock simulated_time
      await handleCalculateRoute(updatedClock.simulated_time);
    } catch (err: any) {
      if (currentSeq !== timelineSeqRef.current) return;
      setErrorMessage(err.message || "Failed to advance scenario.");
    }
  };

  // Node click selection from map
  const handleNodeClick = (nodeId: string) => {
    if (!origin || (origin && destination)) {
      setOrigin(nodeId);
      setDestination("");
    } else {
      setDestination(nodeId);
    }
  };

  // Swap origin and destination
  const handleSwapNodes = () => {
    setOrigin(destination);
    setDestination(origin);
  };

  // Select alternative route to display
  const handleSelectRoute = (key: string, route: RouteAlternative | null) => {
    setActiveRouteKey(key);
    setActiveRoute(route);
  };

  // Map segments using city or scene data with defensive coordinate normalization
  const rawSegments = city?.road_segments || sceneData?.road_segments || [];
  const canvasSegments: RoadSegment[] = rawSegments.map((s: any) => ({
    id: s.id,
    node_a: s.from_intersection || s.node_a,
    node_b: s.to_intersection || s.node_b,
    length_m: s.length_m,
    width_px: 40,
    zone: s.zone,
    centerline: s.centerline,
    polygon: s.polygon,
  }));

  // Authentic synthetic hazards from scene data
  const sceneHazards = sceneData?.hazards || [];
  const sceneBuildings = sceneData?.buildings || [];
  const canvasIntersections = (city?.intersections ||
    sceneData?.intersections ||
    []) as any;

  return (
    <div className="space-y-6">
      {/* Top Banner and Quick Recalculate */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/60 border border-slate-800 p-4 rounded-xl">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-sky-500/20 text-sky-400 flex items-center justify-center border border-sky-500/30">
            <Navigation className="w-4 h-4" />
          </div>
          <div>
            <h2 className="font-bold text-sm text-white">
              Emergency Dispatch & Corridor Route Evaluation
            </h2>
            <p className="text-[11px] text-slate-400">
              Condition-aware routing engine avoiding confirmed blockages with
              table-driven cost penalties.
            </p>
          </div>
        </div>

        <button
          onClick={() => handleCalculateRoute()}
          disabled={recommendMutation.isPending || isCityLoading}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 transition font-medium border border-slate-700"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${recommendMutation.isPending ? "animate-spin" : ""}`}
          />
          Recalculate Route
        </button>
      </div>

      {/* Main Grid Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Interactive SceneCanvas Map */}
        <div className="lg:col-span-7 flex flex-col gap-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-xl">
            <div className="flex items-center justify-between mb-2 px-1 text-xs text-slate-400">
              <span>
                Interactive Road Canvas — Click node to set origin / destination
              </span>
              <span className="font-mono text-sky-400">
                Active Route: {activeRouteKey.toUpperCase()}
              </span>
            </div>

            <SceneCanvas
              sceneImageUrl="/scenarios/demo_city/image_plain.png"
              segments={canvasSegments}
              intersections={canvasIntersections}
              buildings={sceneBuildings}
              hazards={sceneHazards}
              segmentStates={segmentStates}
              selectedRoutePath={activeRoute?.segment_path || []}
              baselineRoutePath={
                recommendation?.baseline_route?.segment_path || []
              }
              recommendedRoutePath={
                recommendation?.recommended_route?.segment_path || []
              }
              originNode={origin}
              destNode={destination}
              onNodeClick={handleNodeClick}
              className="w-full"
            />
          </div>

          {/* Road Status and Map Styles Legend */}
          <RouteLegend />
        </div>

        {/* Right Column: Controls, Summary, Alerts, and Comparison */}
        <div className="lg:col-span-5 flex flex-col gap-4">
          {/* Controls: Origin, Destination, Scenario Progression */}
          <RouteControls
            city={city || null}
            origin={origin}
            destination={destination}
            onOriginChange={setOrigin}
            onDestinationChange={setDestination}
            onSwapNodes={handleSwapNodes}
            onCalculateRoute={() => handleCalculateRoute()}
            isCalculating={recommendMutation.isPending}
            scenario={scenario || null}
            onAdvanceScenario={handleAdvanceScenario}
            isAdvancing={advanceMutation.isPending}
            clockTime={clock?.simulated_time || null}
            clockMode={clock?.clock_mode || "wall-clock"}
            error={errorMessage}
          />

          {/* Corridor Alerts & Constraint Warnings */}
          <RouteWarnings
            alerts={latestAlerts}
            verification={recommendation?.verification}
            warnings={recommendation?.warnings}
          />

          {/* Primary Recommended Route Summary */}
          <RouteSummary recommendation={recommendation} />

          {/* Route Alternatives Selection and Comparison */}
          <RouteComparison
            recommendation={recommendation}
            activeRouteKey={activeRouteKey}
            onSelectRoute={handleSelectRoute}
          />
        </div>
      </div>
    </div>
  );
};

export default RouteScreen;

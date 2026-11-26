import React, { useEffect, useState } from "react";
import { SceneCanvas } from "./SceneCanvas";
import { SceneData, SegmentState } from "../../types/scene";

export const SceneViewerPage: React.FC = () => {
  const [selectedSceneId, setSelectedSceneId] = useState("S-0001");
  const [scene, setScene] = useState<SceneData | null>(null);
  const [states, setStates] = useState<Record<string, SegmentState>>({});
  const [selectedRoute, setSelectedRoute] = useState<string[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);

    Promise.all([
      fetch(`/datasets/v1/${selectedSceneId}/scene.json`).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetch(`/datasets/v1/${selectedSceneId}/ground_truth.json`).then((r) =>
        r.ok ? r.json() : null,
      ),
    ])
      .then(([sceneJson, gtJson]) => {
        if (cancelled) return;
        if (!sceneJson) {
          setLoadError(
            `Scene ${selectedSceneId} assets not found under /datasets/v1/. Copy dev fixtures into frontend/public/datasets/v1/ to browse locally.`,
          );
          setScene(null);
          setStates({});
          return;
        }
        setScene(sceneJson);
        const mapped: Record<string, SegmentState> = {};
        if (gtJson?.segment_statuses) {
          gtJson.segment_statuses.forEach((entry: SegmentState) => {
            mapped[entry.segment_id] = entry;
          });
        }
        setStates(mapped);
        setSelectedRoute([]);
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedSceneId]);

  return (
    <div>
      <div className="page-heading">
        <div>
          <div className="eyebrow">SYNTHETIC SCENE VIEWER / DEV SPLIT</div>
          <h1>Scene viewer</h1>
          <p>
            Inspect synthetic disaster-city geometry, 20-cross-section ground
            truth, and hazard overlays.
          </p>
        </div>
        <div className="heading-actions">
          <label className="run-picker">
            Scene
            <select
              value={selectedSceneId}
              onChange={(e) => setSelectedSceneId(e.target.value)}
            >
              {["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"].map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {loadError && <div className="dl-alert-err">{loadError}</div>}

      <div className="dl-two-col">
        <SceneCanvas
          sceneImageUrl={`/datasets/v1/${selectedSceneId}/image_plain.png`}
          segments={scene?.road_segments ?? []}
          intersections={scene?.intersections ?? []}
          buildings={scene?.buildings ?? []}
          hazards={scene?.hazards ?? []}
          segmentStates={states}
          selectedRoutePath={selectedRoute}
          onSegmentClick={(segId) =>
            setSelectedRoute((prev) =>
              prev.includes(segId)
                ? prev.filter((id) => id !== segId)
                : [...prev, segId],
            )
          }
        />

        <section className="panel scene-detail">
          <div className="panel-head">
            <div>
              <h2>Scene {selectedSceneId} summary</h2>
              <p>
                Difficulty: {scene?.difficulty ?? "—"} · Grid:{" "}
                {scene ? `${scene.grid_size}×${scene.grid_size}` : "—"}
              </p>
            </div>
          </div>
          <div className="scene-columns">
            <h3>Metric</h3>
            <h3>Value</h3>
            <h3>Notes</h3>
            <div className="scene-row">
              <b>Intersections</b>
              <span>{scene?.intersections.length ?? 0}</span>
              <span>Nodes N1..N{scene?.intersections.length ?? 0}</span>
            </div>
            <div className="scene-row">
              <b>Road segments</b>
              <span>{scene?.road_segments.length ?? 0}</span>
              <span>20 perpendicular slices each</span>
            </div>
            <div className="scene-row">
              <b>Buildings</b>
              <span>{scene?.buildings.length ?? 0}</span>
              <span>Block interiors</span>
            </div>
            <div className="scene-row">
              <b>Hazards</b>
              <span>{scene?.hazards.length ?? 0}</span>
              <span>Spec-driven placement</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

export default SceneViewerPage;

import type { SceneRecord } from "../../types";

const pretty = (value: unknown) =>
  value === undefined
    ? "—"
    : typeof value === "string"
      ? value
      : JSON.stringify(value);

export function SceneComparison({ scene }: { scene: SceneRecord }) {
  const truthSegments = (scene.truth.segments ?? {}) as Record<string, unknown>;
  const predictedSegments = (scene.prediction.segments ?? {}) as Record<
    string,
    unknown
  >;
  const segmentIds = [
    ...new Set([
      ...Object.keys(truthSegments),
      ...Object.keys(predictedSegments),
    ]),
  ].sort();
  const items: Array<[string, unknown, unknown]> = [
    [
      "Damaged buildings",
      scene.truth.damaged_building_count,
      scene.prediction.damaged_building_count,
    ],
    [
      "Hazards",
      Array.isArray(scene.truth.hazards)
        ? scene.truth.hazards.length
        : undefined,
      Array.isArray(scene.prediction.hazards)
        ? scene.prediction.hazards.length
        : undefined,
    ],
    [
      "Water regions",
      Array.isArray(scene.truth.water_regions)
        ? scene.truth.water_regions.length
        : undefined,
      Array.isArray(scene.prediction.water_regions)
        ? scene.prediction.water_regions.length
        : undefined,
    ],
    ["Route answers", scene.truth.routes, scene.prediction.routes],
    [
      "Zone comparisons",
      scene.truth.zone_comparisons,
      scene.prediction.zone_comparisons,
    ],
  ];
  return (
    <section className="panel scene-detail">
      <div className="panel-head">
        <div>
          <h2>Scene {scene.scene_id}</h2>
          <p>
            {scene.difficulty ?? "Unrated"} difficulty · Prediction and ground
            truth side by side
          </p>
        </div>
      </div>
      <div className="scene-columns">
        <h3>Measure</h3>
        <h3>Ground truth</h3>
        <h3>Prediction</h3>
        {items.map(([label, truth, prediction]) => (
          <div className="scene-row" key={String(label)}>
            <b>{label}</b>
            <span>{pretty(truth)}</span>
            <span>{pretty(prediction)}</span>
          </div>
        ))}
      </div>
      <h3 className="scene-subtitle">Road segments</h3>
      {segmentIds.length ? (
        <div className="scene-columns">
          <h3>Segment</h3>
          <h3>Ground truth</h3>
          <h3>Prediction</h3>
          {segmentIds.map((id) => (
            <div className="scene-row" key={id}>
              <b>{id}</b>
              <span>{pretty(truthSegments[id])}</span>
              <span>{pretty(predictedSegments[id])}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-state">No segment-level answers for this scene.</p>
      )}
      <details className="raw-json">
        <summary>Show full scene response</summary>
        <pre>
          {JSON.stringify(
            { truth: scene.truth, prediction: scene.prediction },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}

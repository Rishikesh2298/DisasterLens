import React, { useEffect, useState } from "react";
import { SceneCanvas } from "../scene/SceneCanvas";
import { ScenarioPlayer } from "./ScenarioPlayer";
import { ScenarioData, SceneData, SegmentState } from "../../types/scene";

export const ScenarioPlayerPage: React.FC = () => {
  const [demoScene, setDemoScene] = useState<SceneData | null>(null);
  const [scenario, setScenario] = useState<ScenarioData | undefined>(undefined);
  const [demoStates, setDemoStates] = useState<Record<string, SegmentState>>(
    {},
  );
  const [selectedRoute, setSelectedRoute] = useState<string[]>(["SEG-001"]);

  useEffect(() => {
    fetch("/scenarios/demo_city/scene.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setDemoScene(data);
      })
      .catch(() => {});

    fetch("/scenarios/demo_city/scenario.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setScenario(data);
      })
      .catch(() => {});
  }, []);

  return (
    <div>
      <div className="page-heading">
        <div>
          <div className="eyebrow">DEMO CITY / T0–T3 REPLAY</div>
          <h1>Scenario player</h1>
          <p>
            Replay timestamped synthetic camera observations and observe how
            simulated clock changes affect freshness.
          </p>
        </div>
      </div>

      <div className="dl-two-col">
        <SceneCanvas
          sceneImageUrl="/scenarios/demo_city/image_plain.png"
          segments={demoScene?.road_segments ?? []}
          intersections={demoScene?.intersections ?? []}
          buildings={demoScene?.buildings ?? []}
          hazards={demoScene?.hazards ?? []}
          segmentStates={demoStates}
          selectedRoutePath={selectedRoute}
          onSegmentClick={(segId) =>
            setSelectedRoute((prev) =>
              prev.includes(segId)
                ? prev.filter((id) => id !== segId)
                : [...prev, segId],
            )
          }
        />

        <ScenarioPlayer
          scenario={scenario}
          onClockChanged={(_clockIso, updatedStates) =>
            setDemoStates(updatedStates)
          }
        />
      </div>
    </div>
  );
};

export default ScenarioPlayerPage;

import type { Failure, Run, RunIndex, SceneRecord } from "../types";
import mockRun from "../mocks/run.json";
import mockAlwaysClear from "../mocks/run-always-clear.json";
import mockProximity from "../mocks/run-proximity.json";
import mockFailures from "../mocks/failures.json";
import mockScenes from "../mocks/per-scene.json";

const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const mockParameter = new URLSearchParams(window.location.search).get("mock");
const mocks =
  mockParameter === null
    ? import.meta.env.VITE_USE_MOCKS !== "false"
    : mockParameter !== "false";
export const mocksEnabled = mocks;

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${base}${path}`);
  if (!response.ok)
    throw new Error(`Benchmark API returned ${response.status}`);
  return response.json() as Promise<T>;
}

const mockRunMap: Record<string, Run> = {
  [mockRun.run_name]: mockRun as Run,
  [mockAlwaysClear.run_name]: mockAlwaysClear as Run,
  [mockProximity.run_name]: mockProximity as Run,
};

export async function listRuns(): Promise<{ runs: RunIndex[] }> {
  if (mocks)
    return {
      runs: Object.values(mockRunMap).map((run) => ({
        id: run.run_name,
        run_name: run.run_name,
        model_id: run.model_id,
        split: run.split,
        is_mock: run.is_mock,
        scene_count: run.scene_count,
      })),
    };
  return get<{ runs: RunIndex[] }>("/api/benchmark/runs");
}

export async function getRun(id: string): Promise<Run> {
  return mocks
    ? (mockRunMap[id] ?? (mockRun as Run))
    : get<Run>(`/api/benchmark/runs/${encodeURIComponent(id)}`);
}

export async function getFailures(id: string): Promise<Failure[]> {
  if (mocks) return mockFailures as Failure[];
  const result = await get<{ failures: Failure[] }>(
    `/api/benchmark/runs/${encodeURIComponent(id)}/failures`,
  );
  return result.failures;
}

export async function getScene(
  id: string,
  sceneId: string,
): Promise<SceneRecord> {
  if (mocks) {
    const scene = (mockScenes as SceneRecord[]).find(
      (item) => item.scene_id === sceneId,
    );
    if (!scene) throw new Error(`Scene ${sceneId} is not in the mock fixture.`);
    return scene;
  }
  return get<SceneRecord>(
    `/api/benchmark/runs/${encodeURIComponent(id)}/scenes/${encodeURIComponent(sceneId)}`,
  );
}

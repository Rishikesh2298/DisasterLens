export type Failure = {
  scene_id: string;
  category: string;
  question?: string;
  prediction?: unknown;
  truth?: unknown;
  difficulty?: string;
};

export type Metric = {
  task: string;
  metrics: Record<string, number | null>;
  details: Record<string, unknown>;
};
export type RunIndex = {
  id: string;
  run_name: string;
  model_id: string;
  split: string;
  is_mock: boolean;
  scene_count: number;
};
export type SceneRecord = {
  scene_id: string;
  difficulty?: string;
  truth: Record<string, unknown>;
  prediction: Record<string, unknown>;
};
export type Run = {
  id?: string;
  run_name: string;
  model_id: string;
  prompt_version?: string;
  split: string;
  is_mock: boolean;
  scene_count: number;
  created_at: string;
  metrics: Record<string, Metric>;
  route_impact: {
    unsafe_route_rate?: number;
    unnecessary_detour_rate?: number;
    mean_extra_distance_percent?: number;
    by_difficulty?: Record<
      string,
      { unsafe_rate?: number; unnecessary_detour_rate?: number }
    >;
  };
};

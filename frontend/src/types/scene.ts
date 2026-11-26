export type RoadStatus =
  | "blocked"
  | "partial"
  | "clear"
  | "uncertain"
  | "stale"
  | "unknown"
  | "BLOCKED"
  | "PARTIAL"
  | "CLEAR"
  | "UNCERTAIN"
  | "STALE"
  | "UNKNOWN";

export type NormalizedRoadStatus =
  "BLOCKED" | "PARTIAL" | "CLEAR" | "UNCERTAIN" | "STALE" | "UNKNOWN";

export function normalizeStatus(status?: string): NormalizedRoadStatus {
  switch ((status ?? "unknown").toUpperCase()) {
    case "BLOCKED":
      return "BLOCKED";
    case "PARTIAL":
      return "PARTIAL";
    case "CLEAR":
      return "CLEAR";
    case "UNCERTAIN":
      return "UNCERTAIN";
    case "STALE":
      return "STALE";
    default:
      return "UNKNOWN";
  }
}

export type HazardType =
  "flood" | "debris" | "fallen_tree" | "road_damage" | "damaged_building";

export type Zone = "NW" | "NE" | "SW" | "SE";

export interface Point {
  x: number;
  y: number;
}

export interface BBox {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface Intersection {
  id: string;
  x: number;
  y: number;
  zone: Zone;
}

export interface RoadSegment {
  id: string;
  node_a: string;
  node_b: string;
  centerline: Point[];
  polygon: Point[];
  length_m: number;
  width_px: number;
  zone: Zone;
}

export interface Building {
  id: string;
  polygon: Point[];
  zone: Zone;
}

export interface Park {
  id: string;
  polygon: Point[];
  zone: Zone;
}

export interface Hazard {
  id: string;
  type: HazardType;
  placement?: string;
  polygon: Point[];
  bbox: BBox;
  severity?: "minor" | "major";
  affected_road?: string;
  affected_building?: string;
}

export interface SegmentState {
  segment_id: string;
  status: RoadStatus;
  max_coverage?: number;
  blocking_hazards?: string[];
  captured_at?: string;
  age_hours?: number;
  source?: string;
  confidence?: number;
}

export interface SceneData {
  scene_id: string;
  seed: number;
  difficulty: "easy" | "medium" | "hard";
  grid_size: number;
  image_width: number;
  image_height: number;
  intersections: Intersection[];
  road_segments: RoadSegment[];
  buildings: Building[];
  parks: Park[];
  hazards: Hazard[];
}

export interface Observation {
  source: string;
  capture_time: string;
  zone: Zone;
  affected_segments: string[];
  hazard_type?: HazardType | null;
  near_miss?: boolean;
  recovery?: boolean;
  image?: string;
}

export interface ScenarioEvent {
  time_step: string;
  timestamp: string | null;
  description: string;
  observations: Observation[];
}

export interface CameraView {
  camera_id: string;
  zone: Zone;
  viewport: BBox;
  covered_segments: string[];
}

export interface ScenarioData {
  scenario_id: string;
  description: string;
  grid_size: number;
  seed: number;
  cameras: CameraView[];
  events: ScenarioEvent[];
  scene_file: string;
  ground_truth_file: string;
}

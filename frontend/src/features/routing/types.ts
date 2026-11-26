/**
 * TypeScript types and contracts for the routing feature.
 * Strictly aligned with backend Pydantic models in dl/contracts/routing.py
 * and dl/contracts/observation.py.
 */

import { RoadStatus, SegmentState } from "../../types/scene";

export interface RouteStep {
  step_number: number;
  from_node: string;
  to_node: string;
  segment_id: string;
  length_m: number;
  status: RoadStatus;
  freshness: string;
  age_hours: number | null;
  cost_multiplier: number;
  step_cost: number;
  is_stale_from_blocked: boolean;
  warning: string | null;
}

export interface RouteAlternative {
  rank: number;
  is_baseline: boolean;
  node_path: string[];
  segment_path: string[];
  total_length_m: number;
  total_cost: number;
  unverified_segments_count: number;
  has_fresh_blocked: boolean;
  is_valid: boolean;
  steps: RouteStep[];
}

export interface RouteVerification {
  is_valid: boolean;
  is_connected: boolean;
  starts_at_origin: boolean;
  ends_at_destination: boolean;
  has_fresh_blocked_segments: boolean;
  blocked_segment_ids: string[];
  unverified_segment_ids: string[];
  unverified_count: number;
  failure_reasons: string[];
}

export interface RouteRecommendation {
  origin: string;
  destination: string;
  as_of: string;
  risk_mode: string;
  baseline_route: RouteAlternative | null;
  recommended_route: RouteAlternative | null;
  alternatives: RouteAlternative[];
  verification: RouteVerification;
  explanation: string;
  warnings: string[];
}

export interface RouteRecommendRequest {
  city_id?: string;
  origin: string;
  destination: string;
  as_of?: string | null;
  risk_mode?: string;
  save_as?: string | null;
  route_name?: string | null;
}

export interface CitySummary {
  id: string;
  name: string;
  grid_size: number;
  bounds: {
    x_min: number;
    x_max: number;
    y_min: number;
    y_max: number;
  };
}

export interface CityDetails extends CitySummary {
  intersections_count: number;
  segments_count: number;
  zones?: string[];
  scene_image_url?: string;
  scene_image_urls?: { plain: string; labelled: string };
  graph?: { node_count: number; edge_count: number; is_connected: boolean };
  intersections: Array<{
    id: string;
    x: number;
    y: number;
    zone: string;
    connected_segments?: string[];
  }>;
  road_segments: Array<{
    id: string;
    from_intersection: string;
    to_intersection: string;
    node_a?: string;
    node_b?: string;
    length_m: number;
    zone: string;
    centerline: Array<{ x: number; y: number }>;
    polygon: Array<{ x: number; y: number }>;
  }>;
}

export interface CitySegmentsResponse {
  city_id: string;
  as_of: string;
  segments_count: number;
  segments: Record<string, SegmentState>;
}

export interface ScenarioSummary {
  id: string;
  city_id: string;
  description: string;
  current_time_step: string;
  current_simulated_time: string | null;
}

export interface ScenarioDetails extends ScenarioSummary {
  cameras: Array<any>;
  timeline_events: Array<{
    time_step: string;
    timestamp: string | null;
    description: string;
    observations_count: number;
  }>;
}

export interface RouteAlertItem {
  route_id: string;
  alert_type: "PRIMARY_NOW_BLOCKED" | "ROUTE_CLEARED" | "ROUTE_DEGRADED";
  segment_id: string;
  message: string;
  severity: "critical" | "warning" | "info";
}

export interface ScenarioAdvanceResponse {
  scenario_id: string;
  time_step: string;
  timestamp: string | null;
  description: string;
  observations_count: number;
  affected_segments: string[];
  previous_statuses: Record<string, string>;
  new_statuses: Record<string, string>;
  alerts: RouteAlertItem[];
}

export interface ClockResponse {
  clock_mode: "simulated" | "wall-clock";
  reference_time: string;
  simulated_time: string | null;
  wall_clock_time?: string;
}

/**
 * API client functions for DisasterLens routing and backend services.
 */

import {
  CityDetails,
  CitySegmentsResponse,
  CitySummary,
  ClockResponse,
  RouteRecommendation,
  RouteRecommendRequest,
  ScenarioAdvanceResponse,
  ScenarioDetails,
  ScenarioSummary,
} from './types';
import { SegmentState } from '../../types/scene';

const normalizeApiBase = (url: string | undefined): string => {
  if (!url) return '/api';
  let trimmed = url.trim().replace(/\/+$/, '');
  if (!trimmed.endsWith('/api') && !trimmed.includes('/api/')) {
    trimmed = `${trimmed}/api`;
  }
  return trimmed;
};

export const API_BASE = normalizeApiBase(import.meta.env.VITE_API_BASE_URL);

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}: ${res.statusText}`;
    try {
      const errJson = await res.json();
      if (errJson.detail) {
        errorDetail = errJson.detail;
      }
    } catch {
      // Use fallback errorDetail
    }
    throw new Error(errorDetail);
  }
  return res.json() as Promise<T>;
}

export async function fetchCities(): Promise<CitySummary[]> {
  const res = await fetch(`${API_BASE}/cities`);
  return handleResponse<CitySummary[]>(res);
}

export async function fetchCity(cityId: string): Promise<CityDetails> {
  const res = await fetch(`${API_BASE}/cities/${cityId}`);
  return handleResponse<CityDetails>(res);
}

export async function fetchCitySegments(
  cityId: string,
  asOf?: string | null
): Promise<Record<string, SegmentState>> {
  const url = asOf
    ? `${API_BASE}/cities/${cityId}/segments?as_of=${encodeURIComponent(asOf)}`
    : `${API_BASE}/cities/${cityId}/segments`;
  const res = await fetch(url);
  const data = await handleResponse<CitySegmentsResponse>(res);
  return data.segments;
}

export async function recommendRoute(
  req: RouteRecommendRequest
): Promise<RouteRecommendation> {
  const res = await fetch(`${API_BASE}/routes/recommend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      city_id: req.city_id || 'DEMO-001',
      origin: req.origin,
      destination: req.destination,
      as_of: req.as_of || null,
      risk_mode: req.risk_mode || 'normal',
      save_as: req.save_as || null,
      route_name: req.route_name || null,
    }),
  });
  return handleResponse<RouteRecommendation>(res);
}

export async function fetchScenarios(): Promise<ScenarioSummary[]> {
  const res = await fetch(`${API_BASE}/scenarios`);
  return handleResponse<ScenarioSummary[]>(res);
}

export async function fetchScenario(scenarioId: string): Promise<ScenarioDetails> {
  const res = await fetch(`${API_BASE}/scenarios/${scenarioId}`);
  return handleResponse<ScenarioDetails>(res);
}

export async function advanceScenario(
  scenarioId: string,
  timeStep?: string
): Promise<ScenarioAdvanceResponse> {
  const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/advance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(timeStep ? { time_step: timeStep } : {}),
  });
  return handleResponse<ScenarioAdvanceResponse>(res);
}

export async function fetchClock(): Promise<ClockResponse> {
  const res = await fetch(`${API_BASE}/clock`);
  return handleResponse<ClockResponse>(res);
}

export async function setClock(simulatedTime: string | null): Promise<ClockResponse> {
  const res = await fetch(`${API_BASE}/clock`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ simulated_time: simulatedTime }),
  });
  return handleResponse<ClockResponse>(res);
}

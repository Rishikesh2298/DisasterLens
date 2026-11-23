/**
 * TanStack Query v5 hooks for DisasterLens routing and scenario state.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  advanceScenario,
  fetchCities,
  fetchCity,
  fetchCitySegments,
  fetchClock,
  fetchScenario,
  fetchScenarios,
  recommendRoute,
  setClock,
} from './api';
import { RouteRecommendRequest } from './types';

export function useCities() {
  return useQuery({
    queryKey: ['cities'],
    queryFn: fetchCities,
  });
}

export function useCity(cityId: string) {
  return useQuery({
    queryKey: ['city', cityId],
    queryFn: () => fetchCity(cityId),
    enabled: Boolean(cityId),
  });
}

export function useCitySegments(cityId: string, asOf?: string | null) {
  return useQuery({
    queryKey: ['citySegments', cityId, asOf],
    queryFn: () => fetchCitySegments(cityId, asOf),
    enabled: Boolean(cityId),
  });
}

export function useScenarios() {
  return useQuery({
    queryKey: ['scenarios'],
    queryFn: fetchScenarios,
  });
}

export function useScenario(scenarioId: string) {
  return useQuery({
    queryKey: ['scenario', scenarioId],
    queryFn: () => fetchScenario(scenarioId),
    enabled: Boolean(scenarioId),
  });
}

export function useClock() {
  return useQuery({
    queryKey: ['clock'],
    queryFn: fetchClock,
    refetchInterval: 10000,
    staleTime: 0,
  });
}

export function useRecommendRoute() {
  return useMutation({
    mutationFn: (req: RouteRecommendRequest) => recommendRoute(req),
  });
}

export function useAdvanceScenario() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ scenarioId, timeStep }: { scenarioId: string; timeStep?: string }) =>
      advanceScenario(scenarioId, timeStep),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['citySegments'] });
      queryClient.invalidateQueries({ queryKey: ['scenarios'] });
      queryClient.invalidateQueries({ queryKey: ['scenario', variables.scenarioId] });
      queryClient.invalidateQueries({ queryKey: ['clock'] });
    },
  });
}

export function useSetClock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (simulatedTime: string | null) => setClock(simulatedTime),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clock'] });
      queryClient.invalidateQueries({ queryKey: ['citySegments'] });
    },
  });
}

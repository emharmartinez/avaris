"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

// One hook per endpoint; query keys start with the endpoint name so a refresh can
// invalidate everything but the job it is polling
// Also while minimized: the poll is what tells the server the app is still open (idle
// shutdown, [server] idle_shutdown_min)
export const useHealth = () =>
  useQuery({
    queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  });

export const useGames = (date: string | null) =>
  useQuery({
    queryKey: ["predictions", date ?? "today"],
    queryFn: () => (date ? api.predictions(date) : api.today()),
  });

export const useGame = (id: string | null) =>
  useQuery({ queryKey: ["game", id], queryFn: () => api.game(id!), enabled: !!id });

export const useTeams = () => useQuery({ queryKey: ["teams"], queryFn: api.teams });

export const useTeamHistory = (id: number | null, season?: string) =>
  useQuery({
    queryKey: ["team", id, season ?? null],
    queryFn: () => api.team(id!, season),
    enabled: id != null,
  });

export const usePerformance = (season?: string) =>
  useQuery({ queryKey: ["performance", season ?? null], queryFn: () => api.performance(season) });

export const useBacktests = () => useQuery({ queryKey: ["backtests"], queryFn: api.backtests });

export const useBacktest = (name: string | null) =>
  useQuery({ queryKey: ["backtest", name], queryFn: () => api.backtest(name!), enabled: !!name });

export const useInjuries = (date: string | null) =>
  useQuery({ queryKey: ["injuries", date], queryFn: () => api.injuries(date!), enabled: !!date });

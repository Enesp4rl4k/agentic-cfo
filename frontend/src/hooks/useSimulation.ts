"use client";

import { useMutation } from "@tanstack/react-query";
import {
  simulateCascade,
  analyzeHeadcount,
  analyzeMarketing,
  analyzeTech,
  getCascadeTriggers,
} from "@/lib/api/simulation";
import type {
  CascadeSimulateRequest,
  HeadcountMDRequest,
  MarketingMDRequest,
  TechInvestMDRequest,
} from "@/lib/api/simulation";

// ── Cascade Simulator hook ────────────────────────────────────────────────────

export function useCascadeSimulator() {
  const mutation = useMutation({
    mutationFn: (req: CascadeSimulateRequest) => simulateCascade(req),
  });

  return {
    result:   mutation.data ?? null,
    loading:  mutation.isPending,
    error:    mutation.error ? String(mutation.error) : null,
    simulate: mutation.mutate,
    simulateAsync: mutation.mutateAsync,
    reset:    mutation.reset,
  };
}

// ── Multi-domain Counterfactual hooks ─────────────────────────────────────────

export function useHeadcountCF() {
  const mutation = useMutation({
    mutationFn: (req: HeadcountMDRequest) => analyzeHeadcount(req),
  });
  return {
    result:       mutation.data ?? null,
    loading:      mutation.isPending,
    error:        mutation.error ? String(mutation.error) : null,
    analyze:      mutation.mutate,
    analyzeAsync: mutation.mutateAsync,
    reset:        mutation.reset,
  };
}

export function useMarketingCF() {
  const mutation = useMutation({
    mutationFn: (req: MarketingMDRequest) => analyzeMarketing(req),
  });
  return {
    result:       mutation.data ?? null,
    loading:      mutation.isPending,
    error:        mutation.error ? String(mutation.error) : null,
    analyze:      mutation.mutate,
    analyzeAsync: mutation.mutateAsync,
    reset:        mutation.reset,
  };
}

export function useTechCF() {
  const mutation = useMutation({
    mutationFn: (req: TechInvestMDRequest) => analyzeTech(req),
  });
  return {
    result:       mutation.data ?? null,
    loading:      mutation.isPending,
    error:        mutation.error ? String(mutation.error) : null,
    analyze:      mutation.mutate,
    analyzeAsync: mutation.mutateAsync,
    reset:        mutation.reset,
  };
}

// ── Cascade triggers (static metadata) ───────────────────────────────────────

export function useCascadeTriggersMeta() {
  return useMutation({
    mutationFn: () => getCascadeTriggers(),
  });
}

// ── Impact display helpers ────────────────────────────────────────────────────

export function impactColor(level: string): string {
  switch (level) {
    case "critical": return "text-red-500";
    case "high":     return "text-orange-500";
    case "medium":   return "text-yellow-500";
    case "low":      return "text-blue-400";
    default:         return "text-muted-foreground";
  }
}

export function impactBg(level: string): string {
  switch (level) {
    case "critical": return "bg-red-500/10 border-red-500/30";
    case "high":     return "bg-orange-500/10 border-orange-500/30";
    case "medium":   return "bg-yellow-500/10 border-yellow-500/30";
    case "low":      return "bg-blue-500/10 border-blue-500/30";
    default:         return "bg-muted/50 border-border";
  }
}

export function domainLabel(domain: string): string {
  const map: Record<string, string> = {
    cfo: "Finans",
    chro: "İnsan Kaynakları",
    cto: "Teknoloji",
    cmo: "Pazarlama",
    coo: "Operasyon",
    risk: "Risk",
    compliance: "Uyumluluk",
  };
  return map[domain] ?? domain.toUpperCase();
}

export function scoreColor(score: number): string {
  if (score >= 5)  return "text-emerald-400";
  if (score >= 2)  return "text-blue-400";
  if (score >= 0)  return "text-yellow-400";
  if (score >= -3) return "text-orange-400";
  return "text-red-400";
}

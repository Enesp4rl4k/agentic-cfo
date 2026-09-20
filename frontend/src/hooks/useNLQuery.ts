"use client";
/**
 * useNLQuery — Natural Language simulation query hook.
 *
 * Wraps POST /advanced/nl-simulate.
 * Accepts a plain-language question (Turkish or English) and returns:
 *   - simulation_type: "headcount" | "cost_reduction" | "price_increase" | "cashflow" | ...
 *   - answer: human-readable Turkish explanation
 *   - simulation_result: raw numbers from the counterfactual engine
 *   - follow_up_questions: suggested follow-up queries
 *   - intent_confidence: 0–1 score of how well the query was understood
 *
 * Usage:
 *   const { ask, result, isLoading, error, reset } = useNLQuery();
 *   await ask("5 mühendis işe alırsam 12 ayda ne olur?", jobId);
 */
import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface NLQueryResult {
  ok: boolean;
  simulation_type: string | null;
  intent_confidence: number;
  extracted_params: Record<string, unknown>;
  answer: string;
  simulation_result: Record<string, unknown> | null;
  follow_up_questions: string[];
  error: string | null;
}

export interface NLQueryState {
  result: NLQueryResult | null;
  isLoading: boolean;
  error: string | null;
  /** The query that produced the current result */
  lastQuery: string | null;
}

// ── Suggested queries by domain ───────────────────────────────────────────────

export const NL_QUERY_SUGGESTIONS = [
  {
    category: "İşe Alım",
    icon: "👥",
    queries: [
      "5 mühendis işe alırsam 12 ayda mali etkisi ne olur?",
      "Satış ekibini 3 kişi büyütürsek gelir artışı ne kadar olur?",
      "Şu anki headcount ile sürdürülebilir büyüme ne kadar?",
    ],
  },
  {
    category: "Maliyet",
    icon: "✂️",
    queries: [
      "Giderleri %15 azaltırsak kârlılık nasıl değişir?",
      "Pazarlama bütçesini yarıya indirirsek ne olur?",
      "Kira maliyetini düşürürsek nakit etkisi nedir?",
    ],
  },
  {
    category: "Fiyatlama",
    icon: "💰",
    queries: [
      "Fiyatları %10 artırırsak gelir ve müşteri kaybı nasıl dengelenir?",
      "Premium plan eklersek ARR'a etkisi ne olur?",
      "Hangi fiyat seviyesinde break-even'a ulaşırım?",
    ],
  },
  {
    category: "Nakit & Senaryo",
    icon: "📊",
    queries: [
      "Nakit 3 ayda biterse şirkete etkisi nedir?",
      "Kötümser senaryoda 6 aylık nakit pisti nedir?",
      "Yeni bir piyasaya girsek ilk yıl maliyeti ne kadar?",
    ],
  },
];

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useNLQuery() {
  const [state, setState] = useState<NLQueryState>({
    result: null,
    isLoading: false,
    error: null,
    lastQuery: null,
  });

  const ask = useCallback(
    async (query: string, jobId?: string | null) => {
      if (!query.trim()) return;

      setState((prev) => ({
        ...prev,
        isLoading: true,
        error: null,
        lastQuery: query,
      }));

      try {
        const res = await apiClient.post<NLQueryResult>("/advanced/nl-simulate", {
          query: query.trim(),
          job_id: jobId ?? null,
        });

        const data = res.data;

        setState({
          result: data,
          isLoading: false,
          error: data.error ?? null,
          lastQuery: query,
        });

        return data;
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? err.message
            : "Simülasyon sorgusu başarısız oldu.";

        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: message,
        }));

        return null;
      }
    },
    []
  );

  const reset = useCallback(() => {
    setState({
      result: null,
      isLoading: false,
      error: null,
      lastQuery: null,
    });
  }, []);

  return {
    ask,
    reset,
    result: state.result,
    isLoading: state.isLoading,
    error: state.error,
    lastQuery: state.lastQuery,
  };
}

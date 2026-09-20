// Shared types for CEO dashboard components

export interface BoardSlide {
  slide_number: number;
  title: string;
  content: string;
  metrics?: Record<string, number>;
}

export interface OKRObjective {
  objective_id: string;
  name: string;
  weight: number; // 0-1
  score: number;  // 0-1
  momentum: "up" | "down" | "stable";
  key_results: Array<{ name: string; progress: number }>;
}

export interface CEOOutlook {
  base_case: number[];
  optimistic: number[];
  pessimistic: number[];
}

export interface CEOResult {
  job_id: string;
  board_deck?: BoardSlide[];
  okr_status?: {
    company_score: number;
    objectives: OKRObjective[];
  };
  financial_summary?: Record<string, unknown>;
  outlook?: CEOOutlook;
  error: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

export function fmt(n: unknown, decimals = 1): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return isNaN(v) ? "—" : v.toFixed(decimals);
}

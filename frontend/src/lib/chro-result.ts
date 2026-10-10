/**
 * Normalizer between what the backend CHRO pipeline returns and what the
 * dashboard renders.
 *
 * The three agents own their metric keys (pinned by backend tests):
 *   headcount    → total_headcount, total_fte, avg_tenure_years,
 *                  recently_hired_count, by_department (dept → headcount),
 *                  alerts, narrative
 *   attrition    → total_departures, early_departure_rate,
 *                  involuntary_departures_count, attrition_reasons
 *                  (reason → count), estimated_replacement_cost,
 *                  alerts, narrative
 *   compensation → total_employees, total_annual_salary,
 *                  total_annual_benefits, total_annual_comp,
 *                  total_equity_shares (sum of the documented
 *                  equity_annual column), below_market_count,
 *                  above_market_count, avg_salary_by_level, alerts,
 *                  narrative
 *   chro_summary → chro_health_score, component_scores, top_risks
 *                  (title/severity/description), quick_wins
 *                  (action/effort/impact), narrative
 *
 * Money arrives in kuruş; the dashboard shows lira. Metrics the pipeline
 * cannot honestly produce stay null so the view renders "—" instead of
 * "undefined". Every entry point (context load, POST /chro/analyze,
 * DomainPanel) normalizes exactly once.
 */

export interface CHROAlert {
  level: string;
  message: string;
}

export interface CHROHeadcountView {
  total_headcount: number;
  total_fte: number | null;
  recent_hires: number;
  avg_tenure_years: number | null;
  /** recent hires − departures, or null when no attrition data exists */
  net_change: number | null;
  by_department: Array<{ dept: string; count: number }>;
  alerts: CHROAlert[];
  narrative: string | null;
}

export interface CHROAttritionView {
  total_departures: number;
  voluntary: number;
  early_rate: number | null;
  /** lira */
  cost: number | null;
  top_reasons: Array<{ reason: string; count: number; pct: number }>;
  alerts: CHROAlert[];
  narrative: string | null;
}

export interface CHROCompensationView {
  /** lira */
  total_payroll: number | null;
  /** lira */
  avg_salary: number | null;
  /** lira — annual equity grants from the equity_annual column */
  equity_burn: number | null;
  /** lira */
  benefits_cost: number | null;
  below_market_pct: number | null;
  above_market_pct: number | null;
  by_level: Array<{ level: string; avg_salary: number; count: number | null }>;
  alerts: CHROAlert[];
  narrative: string | null;
}

export type CHROEffort = "low" | "medium" | "high";

export interface CHROSummaryView {
  score: number | null;
  component_scores: Record<string, number>;
  top_risks: Array<{ severity: string; message: string }>;
  quick_wins: Array<{ action: string; impact: string; effort: CHROEffort }>;
  narrative: string | null;
}

export interface CHROView {
  headcount: CHROHeadcountView | null;
  attrition: CHROAttritionView | null;
  compensation: CHROCompensationView | null;
  summary: CHROSummaryView | null;
  error: string | null;
}

/** The raw payload shape — sections are whatever the pipeline serialized.
 *  A type alias (not an interface) so it carries an implicit index signature
 *  and narrows cleanly through the isRecord guard. */
export type RawCHROResult = {
  job_id?: string;
  headcount?: Record<string, unknown> | null;
  attrition?: Record<string, unknown> | null;
  compensation?: Record<string, unknown> | null;
  chro_summary?: Record<string, unknown> | null;
  error?: string | null;
};

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

/** Kuruş → lira. */
function toLira(v: unknown): number | null {
  const n = num(v);
  return n === null ? null : n / 100;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function alertsOf(section: Record<string, unknown>): CHROAlert[] {
  if (!Array.isArray(section.alerts)) return [];
  return section.alerts
    .filter(isRecord)
    .map((a) => ({ level: str(a.level) ?? "info", message: str(a.message) ?? "" }))
    .filter((a) => a.message !== "");
}

function normalizeEffort(raw: unknown): CHROEffort {
  const v = String(raw ?? "").trim().toLowerCase();
  if (["low", "medium", "high"].includes(v)) return v as CHROEffort;
  // The pipeline writes quick-win effort in Turkish.
  if (["düşük", "dusuk"].includes(v)) return "low";
  if (["yüksek", "yuksek"].includes(v)) return "high";
  return "medium";
}

function normalizeHeadcount(
  raw: Record<string, unknown> | null | undefined,
): CHROHeadcountView | null {
  if (!isRecord(raw)) return null;
  const total = num(raw.total_headcount ?? raw.headcount);
  if (total === null) return null;

  const byDepartmentRaw = isRecord(raw.by_department) ? raw.by_department : {};
  const by_department = Object.entries(byDepartmentRaw)
    .map(([dept, v]) => ({
      dept,
      count: num(isRecord(v) ? v.headcount : v) ?? 0,
    }))
    .filter((d) => d.count > 0)
    .sort((a, b) => b.count - a.count);

  return {
    total_headcount: total,
    total_fte: num(raw.total_fte),
    recent_hires: num(raw.recently_hired_count) ?? 0,
    avg_tenure_years: num(raw.avg_tenure_years),
    net_change: null, // composed in normalizeCHROResult
    by_department,
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function normalizeAttrition(
  raw: Record<string, unknown> | null | undefined,
): CHROAttritionView | null {
  if (!isRecord(raw)) return null;
  const total = num(raw.total_departures ?? raw.total_attritions);
  if (total === null) return null;

  const involuntary = num(raw.involuntary_departures_count) ?? 0;
  const reasonsRaw = isRecord(raw.attrition_reasons) ? raw.attrition_reasons : {};
  const top_reasons = Object.entries(reasonsRaw)
    .map(([reason, c]) => ({
      reason,
      count: num(c) ?? 0,
      pct: total > 0 ? ((num(c) ?? 0) / total) * 100 : 0,
    }))
    .filter((r) => r.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 4);

  return {
    total_departures: total,
    voluntary: Math.max(0, total - involuntary),
    early_rate: num(raw.early_departure_rate),
    cost: toLira(raw.estimated_replacement_cost ?? raw.cost_of_attrition),
    top_reasons,
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function normalizeCompensation(
  raw: Record<string, unknown> | null | undefined,
  headcountLevels: Record<string, number> | null,
): CHROCompensationView | null {
  if (!isRecord(raw)) return null;
  const employees = num(raw.total_employees);
  const totalComp = toLira(raw.total_annual_comp ?? raw.total_payroll);
  if (employees === null && totalComp === null) return null;

  const totalSalary = toLira(raw.total_annual_salary);
  const byLevelRaw = isRecord(raw.avg_salary_by_level)
    ? raw.avg_salary_by_level
    : isRecord(raw.by_level)
      ? raw.by_level
      : {};
  const by_level = Object.entries(byLevelRaw)
    .map(([level, v]) => ({
      level,
      avg_salary: toLira(v) ?? 0,
      count: headcountLevels ? (headcountLevels[level] ?? null) : null,
    }))
    .filter((l) => l.avg_salary > 0)
    .slice(0, 5);

  return {
    total_payroll: totalComp,
    avg_salary:
      totalSalary !== null && employees ? Math.round(totalSalary / employees) : null,
    // Equity is the one money column the parser keeps raw (shares / the
    // documented equity_annual lira value) — no kuruş conversion here.
    equity_burn: num(raw.total_equity_shares ?? raw.equity_burn_annual),
    benefits_cost: toLira(raw.total_annual_benefits ?? raw.benefits_cost_annual),
    below_market_pct:
      employees && num(raw.below_market_count) !== null
        ? (num(raw.below_market_count) as number) / employees
        : null,
    above_market_pct:
      employees && num(raw.above_market_count) !== null
        ? (num(raw.above_market_count) as number) / employees
        : null,
    by_level,
    alerts: alertsOf(raw),
    narrative: str(raw.narrative),
  };
}

function normalizeSummary(
  raw: Record<string, unknown> | null | undefined,
): CHROSummaryView | null {
  if (!isRecord(raw)) return null;
  const score = num(raw.chro_health_score ?? raw.overall_hr_score);

  const top_risks = (Array.isArray(raw.top_risks) ? raw.top_risks : [])
    .filter(isRecord)
    .map((r) => ({
      severity: str(r.severity) ?? "warning",
      message: str(r.message) ?? str(r.description) ?? str(r.title) ?? "",
    }))
    .filter((r) => r.message !== "");

  const quick_wins = (Array.isArray(raw.quick_wins) ? raw.quick_wins : [])
    .filter(isRecord)
    .map((w) => ({
      action: str(w.action) ?? "",
      impact: str(w.impact) ?? str(w.estimated_impact) ?? "",
      effort: normalizeEffort(w.effort),
    }))
    .filter((w) => w.action !== "");

  const component_scores: Record<string, number> = {};
  if (isRecord(raw.component_scores)) {
    for (const [k, v] of Object.entries(raw.component_scores)) {
      const n = num(v);
      if (n !== null) component_scores[k] = n;
    }
  }

  if (score === null && !str(raw.narrative) && top_risks.length === 0) return null;

  return { score, component_scores, top_risks, quick_wins, narrative: str(raw.narrative) };
}

export function normalizeCHROResult(raw: RawCHROResult | null | undefined): CHROView | null {
  if (!isRecord(raw)) return null;

  const headcount = normalizeHeadcount(raw.headcount);
  const attrition = normalizeAttrition(raw.attrition);

  const headcountLevels: Record<string, number> | null = headcount
    ? Object.fromEntries(
        (isRecord(raw.headcount) && isRecord(raw.headcount.by_level)
          ? Object.entries(raw.headcount.by_level)
          : []
      ).flatMap(([level, v]) => {
        const n = num(v);
        return n === null ? [] : [[level, n] as [string, number]];
      }),
    )
    : null;

  const compensation = normalizeCompensation(raw.compensation, headcountLevels);
  const summary = normalizeSummary(raw.chro_summary);
  const error = str(raw.error);

  if (headcount) {
    headcount.net_change = attrition
      ? headcount.recent_hires - attrition.total_departures
      : null;
  }

  if (!headcount && !attrition && !compensation && !summary && !error) return null;

  return { headcount, attrition, compensation, summary, error };
}

/**
 * Runtime contract between what the COO pipeline returns on the wire and the
 * dashboard view. The page used to cast with `as COOResult`, so a renamed or
 * missing backend key surfaced as `undefined`/`NaN` — the bug class the CHRO
 * page hit on 2026-10-14. Both entry points (context hydration, DomainPanel
 * onResult) normalize exactly once; a section without data is null and the
 * view renders "—".
 *
 * Wire keys are the ones the backend COO agents emit (process/resource/sla).
 * Category fields stay plain strings: the pipeline's vocabulary is not
 * guaranteed, and the view colours badges from whatever it receives.
 */

export interface ProcessBottleneck {
  process_name: string;
  cycle_time: number; // days
  throughput: number; // items/day
  wip: number; // work in progress count
  constraint_type: string;
  toc_recommendation: string;
  impact_score: number; // 0-100
}

export interface SLATicket {
  ticket_id: string;
  title: string;
  assigned_to: string;
  created_date: string;
  due_date: string;
  hours_remaining: number;
  /** A 0–1 ordering score from the backend's rule, never a probability. */
  risk_score?: number;
  risk_level?: string;
  priority: string;
  status: string;
}

export interface SLAData {
  tickets: SLATicket[];
  breach_rate: number;
  trend: Array<{ date: string; breach_pct: number }>;
}

export interface COOResult {
  job_id: string;
  processes: ProcessBottleneck[] | null;
  sla: SLAData | null;
  error: string | null;
}

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

function num0(v: unknown): number {
  return num(v) ?? 0;
}

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function strOrNull(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function records(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter(isRecord) : [];
}

function normalizeProcess(raw: Record<string, unknown>): ProcessBottleneck | null {
  const name = str(raw.process_name);
  if (name === "") return null;
  return {
    process_name: name,
    cycle_time: num0(raw.cycle_time),
    throughput: num0(raw.throughput),
    wip: num0(raw.wip),
    constraint_type: str(raw.constraint_type),
    toc_recommendation: str(raw.toc_recommendation),
    impact_score: num0(raw.impact_score),
  };
}

function normalizeTicket(raw: Record<string, unknown>): SLATicket | null {
  const id = str(raw.ticket_id);
  if (id === "") return null;
  const ticket: SLATicket = {
    ticket_id: id,
    title: str(raw.title),
    assigned_to: str(raw.assigned_to),
    created_date: str(raw.created_date),
    due_date: str(raw.due_date),
    hours_remaining: num0(raw.hours_remaining),
    priority: str(raw.priority),
    status: str(raw.status),
  };
  const risk = num(raw.risk_score);
  if (risk !== null) ticket.risk_score = risk;
  const level = strOrNull(raw.risk_level);
  if (level !== null) ticket.risk_level = level;
  return ticket;
}

function normalizeProcesses(raw: unknown): ProcessBottleneck[] | null {
  if (!Array.isArray(raw)) return null;
  const rows = records(raw)
    .map(normalizeProcess)
    .filter((p): p is ProcessBottleneck => p !== null);
  return rows.length > 0 ? rows : null;
}

function normalizeSla(raw: unknown): SLAData | null {
  if (!isRecord(raw)) return null;
  const tickets = records(raw.tickets)
    .map(normalizeTicket)
    .filter((t): t is SLATicket => t !== null);
  const breachRate = num(raw.breach_rate);
  if (tickets.length === 0 && breachRate === null) return null;
  return {
    tickets,
    breach_rate: breachRate ?? 0,
    trend: records(raw.trend).map((p) => ({
      date: str(p.date),
      breach_pct: num0(p.breach_pct),
    })),
  };
}

export function normalizeCOOResult(raw: unknown): COOResult | null {
  if (!isRecord(raw)) return null;

  const processes = normalizeProcesses(raw.processes);
  const sla = normalizeSla(raw.sla);
  const error = strOrNull(raw.error);

  if (!processes && !sla && !error) return null;

  return { job_id: str(raw.job_id), processes, sla, error };
}

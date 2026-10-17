/**
 * Runtime contract between what the CEO orchestrator returns on the wire and
 * the dashboard view. The page used to cast with `as CEOResult` plus three
 * `as CEOResult & {...}` extensions for fields the base type forgot
 * (cross_risks, swot, decision_brief) — types-only, so a renamed backend key
 * surfaced as `undefined` in cards (the bug class the CHRO page hit on
 * 2026-10-14). All four entry points (context hydration, synthesize,
 * analyze-from-job, analyze) normalize exactly once.
 *
 * Wire keys are the ones the backend CEO orchestrator emits
 * (synthesis/strategic_priorities/board_deck/okr agents; api/ceo.py):
 * cross_risks carry `title` (not `description`) and `domains` (a list, not a
 * single `domain`) — the view aliases honestly so the timeline never renders
 * empty text. Money is kuruş.
 */

import type { BoardSlide, CEOOutlook, OKRObjective } from "@/components/ceo/types";
import type { DecisionBrief } from "@/lib/api/semantic";
import { isRecord, num, num0, strOrNull, records } from "@/lib/wire";

export interface CEORiskView {
  domain: string;
  risk_type: string;
  severity: string;
  description: string;
}

export interface CEOSwotView {
  strengths: string[];
  weaknesses: string[];
  opportunities: string[];
  threats: string[];
  strategic_priorities?: string[];
}

export interface CEOPriorityView {
  title: string;
  rationale: string;
  horizon: string;
  owner: string;
  metric: string;
  target_date: string;
}

export interface CEOView {
  job_id: string;
  board_deck: BoardSlide[];
  okr_status: { company_score: number; objectives: OKRObjective[] } | null;
  outlook: CEOOutlook | null;
  financial_summary: Record<string, number> | null;
  cross_risks: CEORiskView[];
  swot: CEOSwotView | null;
  strategic_priorities: CEOPriorityView[];
  decision_brief: DecisionBrief | null;
  error: string | null;
}

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function strList(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((s): s is string => typeof s === "string" && s.trim() !== "")
    : [];
}

function numScores(v: unknown): Record<string, number> | null {
  if (!isRecord(v)) return null;
  const out: Record<string, number> = {};
  for (const [k, value] of Object.entries(v)) {
    const n = num(value);
    if (n !== null) out[k] = n;
  }
  return Object.keys(out).length > 0 ? out : null;
}

function numSeries(v: unknown): number[] | null {
  if (!Array.isArray(v)) return null;
  const out = v.map(num).filter((n): n is number => n !== null);
  return out.length > 0 ? out : null;
}

function normalizeSlide(raw: Record<string, unknown>): BoardSlide | null {
  const title = str(raw.title);
  if (title === "") return null;
  const slide: BoardSlide = {
    slide_number: num0(raw.slide_number),
    title,
    content: str(raw.content),
  };
  const metrics = numScores(raw.metrics);
  if (metrics) slide.metrics = metrics;
  return slide;
}

function normalizeObjective(raw: Record<string, unknown>): OKRObjective | null {
  const name = str(raw.name);
  if (name === "") return null;
  const momentum = str(raw.momentum);
  return {
    objective_id: str(raw.objective_id),
    name,
    weight: num0(raw.weight),
    score: num0(raw.score),
    momentum: momentum === "up" || momentum === "down" ? momentum : "stable",
    key_results: records(raw.key_results).map((kr) => ({
      name: str(kr.name),
      progress: num0(kr.progress),
    })),
  };
}

function normalizeOkrStatus(raw: unknown): CEOView["okr_status"] {
  if (!isRecord(raw)) return null;
  const score = num(raw.company_score);
  if (score === null) return null;
  return {
    company_score: score,
    objectives: records(raw.objectives)
      .map(normalizeObjective)
      .filter((o): o is OKRObjective => o !== null),
  };
}

function normalizeOutlook(raw: unknown): CEOOutlook | null {
  if (!isRecord(raw)) return null;
  const base = numSeries(raw.base_case);
  if (base === null) return null;
  return {
    base_case: base,
    optimistic: numSeries(raw.optimistic) ?? [],
    pessimistic: numSeries(raw.pessimistic) ?? [],
  };
}

function normalizeCrossRisk(raw: Record<string, unknown>): CEORiskView | null {
  // The pipeline writes `title` (and `domains`, a list); the timeline wants a
  // description and a single domain. Alias honestly, never fabricate.
  const description = str(raw.description) || str(raw.title) || str(raw.recommended_action);
  if (description === "") return null;
  const domains = Array.isArray(raw.domains)
    ? raw.domains
    : isRecord(raw.domain)
      ? []
      : [raw.domain];
  const domain = str(raw.domain) || strList(domains)[0] || "cross";
  return {
    domain,
    risk_type: str(raw.risk_type) || str(raw.risk_id) || "",
    severity: str(raw.severity, "medium"),
    description,
  };
}

function normalizeSwot(raw: unknown): CEOSwotView | null {
  if (!isRecord(raw)) return null;
  const view: CEOSwotView = {
    strengths: strList(raw.strengths),
    weaknesses: strList(raw.weaknesses),
    opportunities: strList(raw.opportunities),
    threats: strList(raw.threats),
  };
  const priorities = strList(raw.strategic_priorities);
  if (priorities.length > 0) view.strategic_priorities = priorities;
  const empty =
    view.strengths.length === 0 &&
    view.weaknesses.length === 0 &&
    view.opportunities.length === 0 &&
    view.threats.length === 0;
  return empty ? null : view;
}

function normalizePriority(raw: Record<string, unknown>): CEOPriorityView | null {
  const title = str(raw.title);
  if (title === "") return null;
  return {
    title,
    rationale: str(raw.rationale),
    horizon: str(raw.horizon),
    owner: str(raw.owner),
    metric: str(raw.metric),
    target_date: str(raw.target_date),
  };
}

export function normalizeCEOResult(raw: unknown): CEOView | null {
  if (!isRecord(raw)) return null;

  const board_deck = records(raw.board_deck)
    .map(normalizeSlide)
    .filter((s): s is BoardSlide => s !== null);
  const okr_status = normalizeOkrStatus(raw.okr_status);
  const outlook = normalizeOutlook(raw.outlook);
  const financial_summary = numScores(raw.financial_summary);
  const cross_risks = records(raw.cross_risks)
    .map(normalizeCrossRisk)
    .filter((r): r is CEORiskView => r !== null);
  const swot = normalizeSwot(raw.swot);
  const strategic_priorities = records(raw.strategic_priorities)
    .map(normalizePriority)
    .filter((p): p is CEOPriorityView => p !== null);
  const decision_brief = isRecord(raw.decision_brief)
    ? (raw.decision_brief as unknown as DecisionBrief)
    : null;
  const error = strOrNull(raw.error);

  const empty =
    board_deck.length === 0 &&
    !okr_status &&
    !outlook &&
    !financial_summary &&
    cross_risks.length === 0 &&
    !swot &&
    strategic_priorities.length === 0 &&
    !decision_brief &&
    !error;
  if (empty) return null;

  return {
    job_id: str(raw.job_id),
    board_deck,
    okr_status,
    outlook,
    financial_summary,
    cross_risks,
    swot,
    strategic_priorities,
    decision_brief,
    error,
  };
}

/**
 * Runtime contract between the /risk-cascade endpoints and the risk dashboard.
 * The page already guards `posture &&` and renders `kri_score === null` as
 * "ölçülmedi", but `by_category` / `sources` / `counts` were read unguarded
 * (a missing key would crash Object.entries / .length) and KRI fields went
 * straight into colors — a renamed backend key would surface as `undefined`
 * or a false-calm green. One normalizer at the three API entry points.
 *
 * Honesty rules: an unmeasured value is null ("—"), an unknown posture is
 * `no_data` (never a calm default), an unclassifiable KRI status is `amber`
 * (visible, never green-calm), an unknown trend is null (no arrow).
 * `counts` fall back to values derived from `all_kris` when the wire counts
 * are missing or garbage — derived, never invented.
 */

import type {
  RiskCascadeReport,
  RiskPostureData,
  KRI,
  KRICascadeLink,
  KRIStatus,
  KRITrend,
  RiskPosture,
} from "@/lib/api/risk";

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

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function strOrNull(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function strList(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((s): s is string => typeof s === "string" && s.trim() !== "")
    : [];
}

function records(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter(isRecord) : [];
}

const STATUSES = ["green", "amber", "red"] as const;
const TRENDS = ["improving", "stable", "deteriorating"] as const;
const POSTURES = ["stable", "elevated", "critical", "no_data"] as const;

function asStatus(v: unknown): KRIStatus {
  return (STATUSES as readonly string[]).includes(String(v))
    ? (v as KRIStatus)
    : "amber";
}

function asTrend(v: unknown): KRITrend | null {
  return (TRENDS as readonly string[]).includes(String(v))
    ? (v as KRITrend)
    : null;
}

function asPosture(v: unknown): RiskPosture {
  return (POSTURES as readonly string[]).includes(String(v))
    ? (v as RiskPosture)
    : "no_data";
}

function normalizeKri(raw: Record<string, unknown>): KRI | null {
  const name = str(raw.name);
  if (name === "") return null;
  return {
    name,
    category: str(raw.category),
    current_value: num(raw.current_value),
    unit: str(raw.unit),
    threshold_amber: num(raw.threshold_amber),
    threshold_red: num(raw.threshold_red),
    higher_is_worse: raw.higher_is_worse === true,
    status: asStatus(raw.status),
    trend: asTrend(raw.trend),
    trajectory_months: num(raw.trajectory_months),
    source: str(raw.source),
    evidence: str(raw.evidence),
    cascade_trigger: strOrNull(raw.cascade_trigger),
    cascade_params: isRecord(raw.cascade_params) ? raw.cascade_params : {},
  };
}

function normalizeKris(v: unknown): KRI[] {
  return records(v)
    .map(normalizeKri)
    .filter((k): k is KRI => k !== null);
}

function intOf(v: unknown): number | null {
  const n = num(v);
  return n !== null && n >= 0 ? Math.round(n) : null;
}

function normalizePosture(raw: unknown): RiskPostureData | null {
  if (!isRecord(raw)) return null;
  const all_kris = normalizeKris(raw.all_kris);
  const derived = {
    red: all_kris.filter((k) => k.status === "red").length,
    amber: all_kris.filter((k) => k.status === "amber").length,
    green: all_kris.filter((k) => k.status === "green").length,
    total: all_kris.length,
  };
  const wireCounts = isRecord(raw.counts) ? raw.counts : {};

  const by_category: Record<string, KRI[]> = {};
  if (isRecord(raw.by_category)) {
    for (const [cat, list] of Object.entries(raw.by_category)) {
      by_category[cat] = normalizeKris(list);
    }
  }

  return {
    kri_score: num(raw.kri_score),
    posture: asPosture(raw.posture),
    posture_tr: str(raw.posture_tr, "—"),
    counts: {
      red: intOf(wireCounts.red) ?? derived.red,
      amber: intOf(wireCounts.amber) ?? derived.amber,
      green: intOf(wireCounts.green) ?? derived.green,
      total: intOf(wireCounts.total) ?? derived.total,
    },
    red_kris: normalizeKris(raw.red_kris),
    amber_kris: normalizeKris(raw.amber_kris),
    upcoming_red: normalizeKris(raw.upcoming_red),
    cascade_ready: normalizeKris(raw.cascade_ready),
    all_kris,
    by_category,
    sources: strList(raw.sources),
  };
}

function normalizeCascadeLink(raw: Record<string, unknown>): KRICascadeLink | null {
  const kri_name = str(raw.kri_name);
  if (kri_name === "") return null;
  return {
    kri_name,
    kri_category: str(raw.kri_category),
    kri_status: asStatus(raw.kri_status),
    kri_value: num(raw.kri_value),
    kri_unit: str(raw.kri_unit),
    trigger_type: str(raw.trigger_type),
    trigger_params: isRecord(raw.trigger_params) ? raw.trigger_params : {},
    cascade_result: isRecord(raw.cascade_result) ? raw.cascade_result : null,
    cascade_error: strOrNull(raw.cascade_error),
  };
}

export function normalizeRiskCascadeReport(raw: unknown): RiskCascadeReport | null {
  if (!isRecord(raw)) return null;

  const kri_posture = normalizePosture(raw.kri_posture);
  const cascade_links = records(raw.cascade_links)
    .map(normalizeCascadeLink)
    .filter((l): l is KRICascadeLink => l !== null);
  const total_cascades = intOf(raw.total_cascades) ?? 0;
  const topCascade = isRecord(raw.top_cascade)
    ? {
        kri_name: str(raw.top_cascade.kri_name),
        trigger_type: str(raw.top_cascade.trigger_type),
        cascade_result: isRecord(raw.top_cascade.cascade_result)
          ? raw.top_cascade.cascade_result
          : null,
      }
    : null;

  if (!kri_posture && cascade_links.length === 0 && total_cascades === 0 && !topCascade) {
    return null;
  }

  return {
    kri_posture,
    cascade_links,
    total_cascades,
    critical_count: intOf(raw.critical_count) ?? 0,
    cascade_summary: str(raw.cascade_summary),
    domains_at_risk: strList(raw.domains_at_risk),
    top_cascade: topCascade,
  };
}

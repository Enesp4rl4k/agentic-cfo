"use client";

import { useState, useEffect, useCallback } from "react";
import { useSession } from "next-auth/react";
import {
  Users, Star, TrendingUp, MessageSquare,
  Trash2, RefreshCw, Loader2, AlertCircle, Plus,
  Target, ShieldCheck, CheckCircle2, Clock, XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import {
  getRadarBacktest,
  getDecisionSuccessMetrics,
  type RadarBacktest,
  type DecisionSuccessMetrics,
} from "@/lib/api/pilot";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Invite = {
  id: string;
  code: string;
  email: string | null;
  company_name?: string | null;
  note: string | null;
  used: boolean;
  used_by: string | null;
  used_at: string | null;
  expires_at: string | null;
  created_at: string;
};

type FeedbackEntry = {
  id: string;
  user_id: string | null;
  job_id: string | null;
  nps_score: number | null;
  analysis_rating: number | null;
  accuracy_rating: number | null;
  usefulness_rating: number | null;
  comment: string | null;
  biggest_benefit: string | null;
  biggest_gap: string | null;
  page_context: string | null;
  created_at: string;
};

type Summary = {
  total_responses: number;
  nps_score: number | null;
  avg_analysis_rating: number | null;
  avg_accuracy_rating: number | null;
  avg_usefulness_rating: number | null;
  avg_speed_rating: number | null;
  promoters: number;
  passives: number;
  detractors: number;
  top_benefits: string[];
  top_gaps: string[];
};

type PilotStatus = {
  registration_mode?: string;
  current_users: number;
  available_invites?: number;
};

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color = "text-foreground" }: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-xl font-semibold tabular-nums", color)}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

// ── NPS gauge ─────────────────────────────────────────────────────────────────

function NpsGauge({ score }: { score: number | null }) {
  const { t } = useI18n();
  if (score === null) return <p className="text-sm text-muted-foreground">{t.pilot.noData}</p>;
  const color = score >= 50 ? "text-emerald-400" : score >= 0 ? "text-yellow-400" : "text-destructive";
  return (
    <div className="flex items-end gap-2">
      <span className={cn("text-3xl font-bold tabular-nums", color)}>{score}</span>
      <span className="mb-1 text-xs text-muted-foreground">{t.pilot.npsOutOf}</span>
    </div>
  );
}

// ── Stars display ─────────────────────────────────────────────────────────────

function StarDisplay({ value }: { value: number | null }) {
  if (!value) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <Star key={s} className={cn("h-3.5 w-3.5", s <= Math.round(value) ? "fill-amber-400 text-amber-400" : "text-muted-foreground")} />
      ))}
      <span className="ml-1 text-xs tabular-nums text-muted-foreground">{value.toFixed(1)}</span>
    </span>
  );
}

// ── Radar Backtest Section ────────────────────────────────────────────────────

function RadarBacktestSection({ data }: { data: RadarBacktest }) {
  const { t } = useI18n();
  const fmt = useCurrencyFormat();
  const rb = t.pilot.radarBacktest;

  const tierBadgeColor = {
    HIGH: "bg-emerald-950/30 text-emerald-400 border-emerald-500/30",
    MODERATE: "bg-yellow-950/30 text-yellow-400 border-yellow-500/30",
    LOW: "bg-destructive/10 text-destructive border-destructive/30",
    NO_ACTUAL: "bg-muted text-muted-foreground border-border",
    NO_FORECAST_SNAPSHOT: "bg-muted text-muted-foreground border-border",
    ZERO_ACTUAL: "bg-muted text-muted-foreground border-border",
  }[data.accuracy_tier];

  const tierLabel = {
    HIGH: rb.tierHigh,
    MODERATE: rb.tierModerate,
    LOW: rb.tierLow,
    NO_ACTUAL: rb.tierNoActual,
    NO_FORECAST_SNAPSHOT: rb.tierNoForecastSnapshot,
    ZERO_ACTUAL: rb.tierZeroActual,
  }[data.accuracy_tier];

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold">{rb.heading}</h2>
        </div>
        <span className={cn("rounded border px-2 py-0.5 text-xs font-medium", tierBadgeColor)}>
          {tierLabel}
        </span>
      </div>
      <p className="text-xs text-muted-foreground mb-4">{rb.subheading}</p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{rb.projected}</p>
          <p className="mt-1 text-base font-semibold tabular-nums">
            {data.projected_end_balance_cents !== null
              ? fmt(data.projected_end_balance_cents / 100)
              : rb.noForecastSnapshot}
          </p>
        </div>
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{rb.actual}</p>
          <p className="mt-1 text-base font-semibold tabular-nums">
            {data.actual_proven_balance_cents !== null
              ? fmt(data.actual_proven_balance_cents / 100)
              : rb.noActual}
            {data.actual_proven_balance_cents !== null && data.actual_proven_balance_as_of
              ? ` · ${data.actual_proven_balance_as_of}`
              : null}
          </p>
        </div>
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{rb.variance}</p>
          <p className={cn(
            "mt-1 text-base font-semibold tabular-nums",
            data.variance_cents !== null && data.variance_cents < 0 ? "text-destructive" : "text-foreground"
          )}>
            {data.variance_cents !== null ? fmt(data.variance_cents / 100) : "—"}
          </p>
        </div>
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{rb.variancePct}</p>
          <p className={cn(
            "mt-1 text-base font-semibold tabular-nums",
            data.variance_pct !== null && data.variance_pct > 25 ? "text-destructive" :
            data.variance_pct !== null && data.variance_pct > 10 ? "text-yellow-400" :
            data.variance_pct !== null ? "text-emerald-400" : "text-muted-foreground"
          )}>
            {data.variance_pct !== null ? `${data.variance_pct.toFixed(1)}%` : "—"}
          </p>
        </div>
      </div>

      {data.summary && (
        <p className="mt-3 text-xs text-muted-foreground border-t border-border/50 pt-2.5">
          {data.summary}
        </p>
      )}
    </div>
  );
}

// ── Decision Metrics Section ──────────────────────────────────────────────────

function DecisionMetricsSection({ data }: { data: DecisionSuccessMetrics }) {
  const { t } = useI18n();
  const fmt = useCurrencyFormat();
  const dm = t.pilot.decisionMetrics;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <ShieldCheck className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold">{dm.heading}</h2>
      </div>
      <p className="text-xs text-muted-foreground mb-4">{dm.subheading}</p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5 mb-4">
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{dm.totalRecommendations}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">{data.total_recommendations}</p>
        </div>
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{dm.adoptionRate}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-emerald-400">
            {data.adoption_rate_pct.toFixed(1)}%
          </p>
        </div>
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{dm.correctionRate}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-yellow-400">
            {data.dismissal_rate_pct.toFixed(1)}%
          </p>
        </div>
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{dm.responseRate}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">
            {data.response_rate_pct.toFixed(1)}%
          </p>
        </div>
        <div className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">{dm.totalImpact}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-primary">
            {fmt(data.accepted_expected_amount_cents / 100)}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground border-t border-border/50 pt-3">
        <span className="flex items-center gap-1.5 text-emerald-400">
          <CheckCircle2 className="h-3.5 w-3.5" />
          {dm.adopted}: <strong className="tabular-nums">{data.adopted_count}</strong>
        </span>
        <span className="flex items-center gap-1.5 text-yellow-400">
          <Clock className="h-3.5 w-3.5" />
          {dm.deferred}: <strong className="tabular-nums">{data.deferred_count}</strong>
        </span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <XCircle className="h-3.5 w-3.5" />
          {dm.dismissed}: <strong className="tabular-nums">{data.dismissed_count}</strong>
        </span>
        <span className="flex items-center gap-1.5 text-foreground">
          {dm.unresponded}: <strong className="tabular-nums">{data.unresponded_count}</strong>
        </span>
      </div>

      {data.summary && (
        <p className="mt-3 text-xs text-muted-foreground border-t border-border/50 pt-2.5">
          {data.summary}
        </p>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PilotAdminPage() {
  const { data: session } = useSession();
  const accessToken = (session as any)?.accessToken as string | undefined;
  const { t, locale } = useI18n();
  const p = t.pilot;
  const dateTag = locale === "tr" ? "tr-TR" : "en-US";

  const [invites, setInvites] = useState<Invite[]>([]);
  const [feedback, setFeedback] = useState<FeedbackEntry[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [status, setStatus] = useState<PilotStatus | null>(null);
  const [backtest, setBacktest] = useState<RadarBacktest | null>(null);
  const [decisionMetrics, setDecisionMetrics] = useState<DecisionSuccessMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Generate invite form
  const [genNote, setGenNote] = useState("");
  const [genEmail, setGenEmail] = useState("");
  const [generating, setGenerating] = useState(false);

  const h = useCallback(
    () => ({
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    }),
    [accessToken]
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [invRes, fbRes, sumRes, stRes, btData, dmData] = await Promise.all([
        fetch(`${API_BASE}/api/v1/pilot/invites`, { headers: h() }),
        fetch(`${API_BASE}/api/v1/pilot/feedback?limit=50`, { headers: h() }),
        fetch(`${API_BASE}/api/v1/pilot/feedback/summary`, { headers: h() }),
        fetch(`${API_BASE}/api/v1/pilot/status`),
        getRadarBacktest().catch(() => null),
        getDecisionSuccessMetrics().catch(() => null),
      ]);
      const [invData, fbData, sumData, stData] = await Promise.all([
        invRes.json(), fbRes.json(), sumRes.json(), stRes.json(),
      ]);
      setInvites(invData.data ?? []);
      setFeedback(fbData.data?.entries ?? []);
      setSummary(sumData.data ?? null);
      setStatus(stData.data ?? null);
      setBacktest(btData);
      setDecisionMetrics(dmData);
    } catch {
      setError(p.loadError);
    } finally {
      setLoading(false);
    }
  }, [h, p]);

  useEffect(() => { if (accessToken) loadAll(); }, [accessToken, loadAll]);

  async function generateInvite() {
    setGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/pilot/invite/generate`, {
        method: "POST",
        headers: h(),
        // The invitation link goes to the address by e-mail; the company named here is created when it is used.
        body: JSON.stringify({ company_name: genNote, email: genEmail }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? p.genericError);
      await loadAll();
      setGenNote("");
      setGenEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : p.genericError);
    } finally {
      setGenerating(false);
    }
  }

  async function revokeInvite(id: string) {
    await fetch(`${API_BASE}/api/v1/pilot/invite/${id}`, { method: "DELETE", headers: h() });
    setInvites((prev) => prev.filter((i) => i.id !== id));
  }

  const unusedInvites = invites.filter((i) => !i.used);
  const usedInvites   = invites.filter((i) => i.used);

  return (
    <div className="space-y-6 p-5 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{p.title}</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {p.subtitle}
          </p>
        </div>
        <button
          onClick={loadAll}
          disabled={loading}
          className="flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          {p.refresh}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/8 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Status strip */}
      {status && (
        <div className="grid grid-cols-3 gap-3">
          <StatCard label={p.stats.totalUsers} value={status.current_users} />
          <StatCard label={p.stats.pendingInvites} value={unusedInvites.length} />
          <StatCard label={p.stats.usedInvites} value={usedInvites.length} />
        </div>
      )}

      {/* NPS + ratings */}
      {summary && summary.total_responses > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-4 text-sm font-medium">
            {p.feedback.summary.replace("{count}", String(summary.total_responses))}
          </h2>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-xs text-muted-foreground">{p.feedback.npsScore}</p>
              <NpsGauge score={summary.nps_score} />
              <div className="mt-2 flex gap-3 text-xs">
                <span className="text-emerald-400">😊 {p.feedback.promoters.replace("{count}", String(summary.promoters))}</span>
                <span className="text-yellow-400">😐 {p.feedback.passives.replace("{count}", String(summary.passives))}</span>
                <span className="text-destructive">😞 {p.feedback.detractors.replace("{count}", String(summary.detractors))}</span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{p.feedback.analysisQuality}</span>
                <StarDisplay value={summary.avg_analysis_rating} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{p.feedback.accuracy}</span>
                <StarDisplay value={summary.avg_accuracy_rating} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{p.feedback.usefulness}</span>
                <StarDisplay value={summary.avg_usefulness_rating} />
              </div>
            </div>
          </div>

          {summary.top_benefits.length > 0 && (
            <div className="mt-4">
              <p className="mb-1.5 text-xs font-medium text-emerald-400">{p.feedback.topBenefits}</p>
              <ul className="space-y-1">
                {summary.top_benefits.slice(0, 5).map((b, i) => (
                  <li key={i} className="text-xs text-muted-foreground">• {b}</li>
                ))}
              </ul>
            </div>
          )}

          {summary.top_gaps.length > 0 && (
            <div className="mt-3">
              <p className="mb-1.5 text-xs font-medium text-orange-400">{p.feedback.topGaps}</p>
              <ul className="space-y-1">
                {summary.top_gaps.slice(0, 5).map((g, i) => (
                  <li key={i} className="text-xs text-muted-foreground">• {g}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Radar Backtesting */}
      {backtest && <RadarBacktestSection data={backtest} />}

      {/* Decision Metrics */}
      {decisionMetrics && <DecisionMetricsSection data={decisionMetrics} />}

      {/* Generate invite */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Plus className="h-4 w-4 text-muted-foreground" />
          {p.generate.heading}
        </h2>
        <div className="flex flex-wrap gap-2">
          <input
            type="email"
            value={genEmail}
            onChange={(e) => setGenEmail(e.target.value)}
            placeholder={p.generate.emailPlaceholder}
            className="h-8 flex-1 min-w-[160px] rounded-md border border-border bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <input
            type="text"
            value={genNote}
            onChange={(e) => setGenNote(e.target.value)}
            placeholder={p.generate.notePlaceholder}
            className="h-8 flex-1 min-w-[140px] rounded-md border border-border bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <button
            onClick={generateInvite}
            disabled={generating || !genEmail || !genNote}
            className="flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
            {p.generate.submit}
          </button>
        </div>
      </div>

      {/* Invite list */}
      {invites.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">
              {p.invites.heading.replace("{count}", String(invites.length))}
            </h2>
          </div>
          <div className="divide-y divide-border/50">
            {invites.map((inv) => (
              <div key={inv.id} className={cn("flex items-center gap-3 px-4 py-3", inv.used && "opacity-50")}>
                <span className="flex-1 min-w-0 truncate rounded bg-muted px-2 py-0.5 font-mono text-xs">
                  {inv.company_name ?? inv.code}
                </span>
                {inv.email && <span className="text-xs text-muted-foreground">{inv.email}</span>}
                {inv.used ? (
                  <span className="text-xs text-emerald-400">{p.invites.used}</span>
                ) : (
                  <>
                    <button
                      onClick={() => revokeInvite(inv.id)}
                      className="rounded p-1 text-muted-foreground transition-colors hover:text-destructive"
                      aria-label={p.invites.revoke}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent feedback */}
      {feedback.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">
              {p.recent.heading.replace("{count}", String(feedback.length))}
            </h2>
          </div>
          <div className="divide-y divide-border/50">
            {feedback.slice(0, 10).map((f) => (
              <div key={f.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  {f.nps_score !== null && (
                    <span className={cn(
                      "rounded px-1.5 py-0.5 text-xs font-medium",
                      f.nps_score >= 9 ? "bg-emerald-950/30 text-emerald-400" :
                      f.nps_score >= 7 ? "bg-blue-950/30 text-blue-400" :
                      "bg-destructive/10 text-destructive"
                    )}>
                      {p.recent.npsBadge.replace("{score}", String(f.nps_score))}
                    </span>
                  )}
                  {f.analysis_rating && <StarDisplay value={f.analysis_rating} />}
                  <span className="text-xs text-muted-foreground">
                    {new Date(f.created_at).toLocaleDateString(dateTag)}
                  </span>
                  {f.page_context && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {f.page_context}
                    </span>
                  )}
                </div>
                {f.comment && (
                  <p className="mt-1.5 text-xs text-muted-foreground">{f.comment}</p>
                )}
                {f.biggest_gap && (
                  <p className="mt-1 text-xs text-orange-400/80">❌ {f.biggest_gap}</p>
                )}
                {f.biggest_benefit && (
                  <p className="mt-1 text-xs text-emerald-400/80">✅ {f.biggest_benefit}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {!loading && invites.length === 0 && feedback.length === 0 && !backtest && !decisionMetrics && (
        <div className="rounded-lg border border-border bg-card px-4 py-12 text-center">
          <Users className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium">{p.empty.heading}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {p.empty.body}
          </p>
        </div>
      )}
    </div>
  );
}

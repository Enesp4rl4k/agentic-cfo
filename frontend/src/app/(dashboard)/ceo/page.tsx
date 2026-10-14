"use client";

export const dynamic = "force-dynamic";

import { useState, useEffect } from "react";
import { Download, ShieldAlert, TrendingUp, Users, Cpu, ChevronDown } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ActionCenter } from "@/components/ActionCenter";
import { DomainDataSources } from "@/components/ceo/DomainDataSources";
import { RoleDashboardHeader } from "@/components/ui/role-dashboard-header";

import { BoardDeckViewer }     from "@/components/ceo/BoardDeckViewer";
import { OKRWeightedScorecard } from "@/components/ceo/OKRScorecard";
import { OutlookChart }         from "@/components/ceo/OutlookChart";
import { SWOTWidget }           from "@/components/ceo/SWOTWidget";
import { DecisionBriefPanel } from "@/components/ui/decision-brief-panel";
import { getDecisionBrief, getSemanticHistory, rebuildSemantic, approveDecisionBrief, type DecisionBrief, type SemanticPeriodSummary } from "@/lib/api/semantic";
import { type CEOResult, type BoardSlide, type OKRObjective } from "@/components/ceo/types";
import { normalizeCEOResult, type CEOView } from "@/lib/ceo-result";
import { useCompanyContextStore } from "@/store/companyContext";
import { useI18n } from "@/hooks/useI18n";

// ── PDF export ─────────────────────────────────────────────────────────────────
// Uses /advanced/board-deck-pdf which reads from CompanyContext directly —
// richer output than /ceo/export-pdf (includes all agent results).

function PDFExportButtons({
  jobId,
  orgId,
}: {
  jobId?: string | null;
  orgId?: string | null;
}) {
  const [exporting, setExporting] = useState<"deck" | "one-pager" | null>(null);
  const { t } = useI18n();

  async function handleExport(type: "deck" | "one-pager") {
    setExporting(type);
    try {
      const res = await apiClient.post(
        "/advanced/board-deck-pdf",
        {
          job_id:  jobId  ?? null,
          org_id_param: orgId ?? null,
        },
        { responseType: "blob" }
      );
      const blob = res.data as Blob;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${type === "deck" ? "board-deck" : "one-pager"}-${new Date().toISOString().split("T")[0]}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (process.env.NODE_ENV === "development") {
        console.error("Board deck PDF export failed:", err);
      }
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="flex gap-2">
      <Button
        variant="default"
        size="sm"
        disabled={exporting !== null}
        onClick={() => handleExport("deck")}
        aria-label={t.roleDashboards.ceo.body.downloadBoardDeckPdf}
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        {exporting === "deck" ? t.roleDashboards.ceo.body.downloading : "Board Deck PDF"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={exporting !== null}
        onClick={() => handleExport("one-pager")}
        aria-label={t.roleDashboards.ceo.body.downloadOnePagerPdf}
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        {exporting === "one-pager" ? t.roleDashboards.ceo.body.downloading : "One-Pager PDF"}
      </Button>
    </div>
  );
}

// ── Cross-Risk Timeline ────────────────────────────────────────────────────────

interface CrossRisk {
  domain:    string;
  risk_type: string;
  severity:  string;
  description: string;
}

function CrossRiskTimeline({ risks }: { risks: CrossRisk[] }) {
  const { t } = useI18n();
  if (!risks.length) return null;

  const domainIcon = (d: string) => {
    switch (d) {
      case "finance": return <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />;
      case "tech":    return <Cpu className="h-3.5 w-3.5 text-mapblue-400" />;
      case "hr":      return <Users className="h-3.5 w-3.5 text-sage-400" />;
      default:        return <ShieldAlert className="h-3.5 w-3.5 text-orange-400" />;
    }
  };

  const severityColor = (s: string) =>
    s === "critical" ? "border-red-500/30 bg-red-500/5" :
    s === "high"     ? "border-orange-500/30 bg-orange-500/5" :
    s === "medium"   ? "border-yellow-500/30 bg-yellow-500/5" :
                       "border-border bg-muted/20";

  const severityBadge = (s: string) =>
    s === "critical" ? "bg-red-500/20 text-red-400" :
    s === "high"     ? "bg-orange-500/20 text-orange-400" :
    s === "medium"   ? "bg-yellow-500/20 text-yellow-400" :
                       "bg-muted text-muted-foreground";

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-orange-400" />
        <h3 className="font-semibold text-sm">{t.roleDashboards.ceo.sections.crossDomainRiskTimeline}</h3>
        <span className="rounded-full bg-orange-500/10 border border-orange-500/20 px-1.5 py-0.5 text-[10px] text-orange-400 font-medium">
          {risks.length} {t.roleDashboards.ceo.body.risk}
        </span>
      </div>

      <div className="relative space-y-2 pl-4">
        {/* Vertical timeline line */}
        <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border" />

        {risks.map((risk, i) => (
          <div key={i} className={cn("relative rounded-lg border p-2.5 pl-3", severityColor(risk.severity))}>
            {/* Timeline dot */}
            <div className={cn(
              "absolute -left-[17px] top-3 h-2.5 w-2.5 rounded-full border-2 border-background",
              risk.severity === "critical" ? "bg-red-400" :
              risk.severity === "high"     ? "bg-orange-400" :
              risk.severity === "medium"   ? "bg-yellow-400" : "bg-muted-foreground"
            )} />

            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                {domainIcon(risk.domain)}
                <p className="text-xs font-medium truncate capitalize">{risk.domain}</p>
                <span className={cn("rounded px-1 py-0.5 text-[9px] font-medium tracking-wide", severityBadge(risk.severity))}>
                  {/* JS casing: CSS uppercase follows html lang (tr → "CRITICAL" with dotted I). */}
                  {risk.severity.toUpperCase()}
                </span>
              </div>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground leading-relaxed">{risk.description}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function CEODashboardPage() {
  const { activeCFOJobId, orgId } = useCompanyContextStore();
  const { t } = useI18n();
  const [company, setCompany] = useState("");
  const [period,  setPeriod]  = useState("");
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState<CEOView | null>(null);
  const [error,   setError]   = useState<string | null>(null);
  const [liveLoaded, setLiveLoaded] = useState(false);
  const [brief, setBrief] = useState<DecisionBrief | null>(null);
  const [periodHistory, setPeriodHistory] = useState<SemanticPeriodSummary[]>([]);
  const [selectedPeriod, setSelectedPeriod] = useState<string | undefined>();
  const [rebuildingBrief, setRebuildingBrief] = useState(false);
  const [approvingBrief, setApprovingBrief] = useState(false);
  const [synthesizing, setSynthesizing] = useState(false);

  // Prefer live CompanyContext / last CEO result over SAMPLE CSV paste.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const target = orgId ? `/context/${orgId}` : "/context/me";
        const res = await apiClient.get(target);
        const ctx = res.data?.data ?? res.data;
        if (cancelled || !ctx) return;
        if (ctx.company_name) setCompany(String(ctx.company_name));
        if (ctx.reporting_period) setPeriod(String(ctx.reporting_period));
        const lastCeo = ctx.last_ceo_result;
        if (lastCeo && typeof lastCeo === "object") {
          const view = normalizeCEOResult(lastCeo);
          setResult(view);
          setLiveLoaded(true);
          if (view?.decision_brief) {
            setBrief(view.decision_brief);
          }
        }
      } catch {
        /* empty state until analyze */
      }
      try {
        const b = await getDecisionBrief(selectedPeriod);
        if (!cancelled && b.brief) setBrief(b.brief);
        const periods = await getSemanticHistory(12);
        if (!cancelled) setPeriodHistory(periods);
      } catch {
        /* optional */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgId, selectedPeriod]);

  async function handleApproveBrief() {
    setApprovingBrief(true);
    try {
      const res = await approveDecisionBrief(selectedPeriod);
      if (res.brief) setBrief(res.brief);
    } finally {
      setApprovingBrief(false);
    }
  }

  async function handleRegenerateBrief() {
    setRebuildingBrief(true);
    try {
      await rebuildSemantic();
      const b = await getDecisionBrief(selectedPeriod);
      if (b.brief) setBrief(b.brief);
    } finally {
      setRebuildingBrief(false);
    }
  }

  async function handleSynthesizeFromContext() {
    setSynthesizing(true);
    setError(null);
    try {
      const res = await apiClient.post("/ceo/synthesize", {});
      const data = res.data?.data ?? res.data;
      if (res.data?.error) throw new Error(res.data.error);
      if (data) {
        setResult(normalizeCEOResult(data));
        setLiveLoaded(true);
      }
      const b = await getDecisionBrief(selectedPeriod);
      if (b.brief) setBrief(b.brief);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t.roleDashboards.ceo.body.synthesisFailed);
    } finally {
      setSynthesizing(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // Prefer analyze-from-job when CFO context exists (no SAMPLE transactions).
      if (activeCFOJobId) {
        const res = await apiClient.post(`/ceo/analyze-from-job/${activeCFOJobId}`, {
          company_name: company || null,
          period: period || null,
        });
        const data = res.data?.data ?? res.data;
        if (res.data?.error) throw new Error(res.data.error);
        setResult(normalizeCEOResult(data));
        setLiveLoaded(true);
      } else {
        const res = await apiClient.post<CEOResult>("/ceo/analyze", {
          company_name: company || null,
          period:       period  || null,
        });
        if (res.data.error) throw new Error(res.data.error);
        setResult(normalizeCEOResult(res.data));
        setLiveLoaded(true);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t.roleDashboards.ceo.body.unknownError);
    } finally {
      setLoading(false);
    }
  }

  const display = result;
  const showEmpty = !display;

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 sm:p-6 xl:p-8">
      {/* Header */}
      <RoleDashboardHeader
        title={t.roleDashboards.ceo.title}
        description={t.roleDashboards.ceo.description}
        context={liveLoaded ? <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden="true" />{t.roleDashboards.ceo.body.currentCompanyContext}</span> : undefined}
      />

      <ActionCenter />

      {/* The three-step flow POST /ceo/analyze-from-job describes in its own
          docstring: upload the statement, attach domain files, run. Neither of
          the last two routes had a door, so every C-level stayed derived. */}
      <DomainDataSources />

      {/* Input form */}
      <details open={!display} className="group rounded-xl border border-border/80 bg-card">
        <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
          <span className="text-sm font-semibold">{display ? t.roleDashboards.ceo.body.newAnalysis : t.roleDashboards.ceo.body.analysisInputs}</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
      <form onSubmit={handleSubmit} className="border-t border-border/80 p-4 sm:p-5">
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="ceo-company">{t.roleDashboards.ceo.body.companyName}</Label>
            <Input
              id="ceo-company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ceo-period">{t.roleDashboards.ceo.body.period}</Label>
            <Input
              id="ceo-period"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2026-H1"
            />
          </div>
        </div>

        {error && (
          <p role="alert" className="mb-3 rounded border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <Button type="submit" disabled={loading}>
          {loading ? t.roleDashboards.ceo.body.preparingAnalysis : activeCFOJobId ? t.roleDashboards.ceo.body.summarizeFromCfo : t.roleDashboards.ceo.body.runAnalysis}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={synthesizing || !orgId}
          onClick={() => void handleSynthesizeFromContext()}
        >
          {synthesizing ? t.roleDashboards.ceo.body.refreshingSummary : t.roleDashboards.ceo.body.refreshExecutiveSummary}
        </Button>
      </form>
      </details>

      {showEmpty ? (
        <div className="space-y-4">
          <DecisionBriefPanel
            brief={brief}
            periodOptions={periodHistory}
            selectedPeriod={selectedPeriod}
            onPeriodChange={(pk) => setSelectedPeriod(pk)}
            onRebuild={() => void handleRegenerateBrief()}
            rebuilding={rebuildingBrief}
            onApprove={() => void handleApproveBrief()}
            approving={approvingBrief}
          />
          <Card className="p-6 text-sm text-muted-foreground">
            {t.roleDashboards.ceo.body.emptyState}
          </Card>
        </div>
      ) : (
        <div className="space-y-6">
          <DecisionBriefPanel
            brief={brief ?? display?.decision_brief ?? null}
            periodOptions={periodHistory}
            selectedPeriod={selectedPeriod}
            onPeriodChange={(pk) => setSelectedPeriod(pk)}
            onRebuild={() => void handleRegenerateBrief()}
            rebuilding={rebuildingBrief}
            onApprove={() => void handleApproveBrief()}
            approving={approvingBrief}
          />
          <PDFExportButtons jobId={activeCFOJobId} orgId={orgId} />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              {display?.board_deck && <BoardDeckViewer slides={display.board_deck} />}
            </div>
            {display?.okr_status && (
              <OKRWeightedScorecard
                companyScore={display.okr_status.company_score}
                objectives={display.okr_status.objectives as OKRObjective[]}
              />
            )}
          </div>
          {display?.outlook && <OutlookChart outlook={display.outlook} />}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <SWOTWidget
              data={result?.swot ?? null}
              jobId={activeCFOJobId}
              orgId={orgId}
            />
            <CrossRiskTimeline
              risks={result?.cross_risks ?? []}
            />
          </div>
        </div>
      )}
    </div>
  );
}

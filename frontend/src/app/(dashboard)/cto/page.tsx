"use client";

import { useAgentJob } from "@/hooks/useAgentJob";
import { AgentJobPanel } from "@/components/ui/agent-job-panel";
import { ProactiveActionCards } from "@/components/ui/proactive-actions";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { healthColor, healthLabel, type CTOResult } from "@/components/cto/types";
import { GitHubConnectorCard } from "@/components/cto/GitHubConnectorCard";
import { DomainPanel } from "@/components/domains/DomainPanel";
import { useCompanyContextStore } from "@/store/companyContext";
import { RoleDashboardHeader } from "@/components/ui/role-dashboard-header";
import { useI18n } from "@/hooks/useI18n";
import { normalizeCTOResult } from "@/lib/cto-result";
import {
  InfraSection,
  TechDebtSection,
  IncidentSection,
  VelocitySection,
} from "@/components/cto/CTOSections";

// ── Input field definitions ────────────────────────────────────────────────────

const INPUT_FIELDS = [
  { labelKey: "cloudBillingCsv", key: "cloud_billing_csv", placeholder: "service,cost,date\nEC2,1234.56,2024-06" },
  { labelKey: "gitLog", key: "git_log_text", placeholder: "commit abc1234\nAuthor: dev@company.com\n..." },
  { labelKey: "incidentCsv", key: "incident_csv", placeholder: "id,severity,service,started_at,resolved_at\n1,critical,api,2024-06-01T10:00:00Z,2024-06-01T14:00:00Z" },
  { labelKey: "sprintCsv", key: "sprint_csv", placeholder: "sprint_name,planned_points,completed_points\nSprint 1,40,36" },
] as const;

// ── Input form ─────────────────────────────────────────────────────────────────

function CTOInputForm({
  onEnqueue,
  disabled,
}: {
  onEnqueue: (data: Record<string, string>) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const [values, setValues] = useState<Record<string, string>>({
    cloud_billing_csv: "",
    git_log_text:      "",
    incident_csv:      "",
    sprint_csv:        "",
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onEnqueue(values);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {t.roleDashboards.cto.body.formHint}
      </p>
      {INPUT_FIELDS.map(({ labelKey, key, placeholder }) => (
        <div key={key} className="space-y-1.5">
          <Label htmlFor={`cto-${key}`}>{t.roleDashboards.cto.body.inputFields[labelKey]}</Label>
          <textarea
            id={`cto-${key}`}
            className="w-full rounded-md border border-border bg-card px-3 py-2 font-mono text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary"
            rows={4}
            placeholder={placeholder}
            value={values[key]}
            onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
          />
        </div>
      ))}

      <Separator />

      <Button type="submit" disabled={disabled}>
        {disabled && <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
        {disabled ? t.roleDashboards.cto.body.analyzing : t.roleDashboards.cto.body.runAnalysis}
      </Button>
    </form>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function CTODashboardPage() {
  const { t } = useI18n();
  const { enqueue, status, progress, logs, error, result, isDone, isActive, reset } =
    useAgentJob("cto");

  // One engine: the CTO orchestrator, on files attached to the job (panel) or
  // pasted below. Nothing is shown that was not computed from real input.
  const { orgId, activeCFOJobId } = useCompanyContextStore();
  const [panelResult, setPanelResult] = useState<CTOResult | null>(null);
  const [panelKey, setPanelKey] = useState(0);

  // Hydrate from the stored result so a completed analysis is still visible on
  // revisit — matches the CMO/COO/CHRO pages (no re-run needed to see it).
  // Not cancelled on re-runs: orgId flips fetch the same snapshot (cmo/page).
  useEffect(() => {
    (async () => {
      try {
        const target = orgId ? `/context/${orgId}` : "/context/me";
        const res = await apiClient.get(target);
        const ctx = res.data?.data ?? res.data;
        const last = ctx?.last_cto_result;
        if (last && typeof last === "object" && last.cto_summary) {
          setPanelResult(normalizeCTOResult(last));
        }
      } catch {
        /* empty until analyze */
      }
    })();
  }, [orgId]);

  const ctoResult: CTOResult | null =
    isDone && result ? normalizeCTOResult(result) : panelResult;

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 sm:p-6 xl:p-8">
      <RoleDashboardHeader
        title={t.roleDashboards.cto.title}
        description={t.roleDashboards.cto.description}
      />

      <DomainPanel
        key={panelKey}
        alan="cto"
        jobId={activeCFOJobId}
        onResult={(r) => {
          if (r) setPanelResult(normalizeCTOResult(r));
        }}
      />

      <GitHubConnectorCard onSynced={() => setPanelKey((k) => k + 1)} />

      {(isActive || status === "failed") && (
        <AgentJobPanel
          status={status}
          progress={progress}
          logs={logs}
          error={error}
          agentLabel="CTO"
          onReset={reset}
        />
      )}

      {ctoResult?.cto_summary && (
        <div className="rounded-xl border border-primary/20 bg-card p-4 sm:p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">{t.roleDashboards.cto.body.healthScoreHeading}</h3>
            <span className={`text-2xl font-bold tabular-nums ${healthColor(ctoResult.cto_summary.overall_health_score)}`}>
              {ctoResult.cto_summary.overall_health_score.toFixed(1)}/10
              <span className="ml-2 text-sm font-normal">
                {healthLabel(ctoResult.cto_summary.overall_health_score, t.roleDashboards.cto.body.healthLabels)}
              </span>
            </span>
          </div>

          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Object.entries(ctoResult.cto_summary.component_scores ?? {}).map(([domain, score]) => (
              <div key={domain} className="text-center">
                <p className="text-[10px] uppercase text-muted-foreground">
                  {domain.replace("_", " ").toUpperCase()}
                </p>
                <p className={`text-base font-bold ${healthColor(score as number)}`}>
                  {(score as number).toFixed(1)}
                </p>
              </div>
            ))}
          </div>

          <p className="mt-3 text-xs italic text-muted-foreground">
            {ctoResult.cto_summary.narrative}
          </p>
        </div>
      )}

      {ctoResult?.cto_summary?.quick_wins && (
        <ProactiveActionCards
          actions={ctoResult.cto_summary.quick_wins}
          agent="cto"
          agentLabel="CTO"
        />
      )}

      {ctoResult ? (
        <div className="space-y-4">
          {ctoResult.incidents && <IncidentSection data={ctoResult.incidents} />}
          {ctoResult.infra     && <InfraSection    data={ctoResult.infra}     />}
          {ctoResult.tech_debt && <TechDebtSection data={ctoResult.tech_debt} />}
          {ctoResult.velocity  && <VelocitySection data={ctoResult.velocity}  />}
          {!ctoResult.infra && !ctoResult.tech_debt && !ctoResult.incidents && !ctoResult.velocity && (
            <p className="text-sm text-muted-foreground">
              {t.roleDashboards.cto.body.noData}
            </p>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card p-6">
          <h3 className="mb-4 text-sm font-semibold">{t.roleDashboards.cto.body.startHeading}</h3>
          <CTOInputForm onEnqueue={enqueue} disabled={isActive} />
        </div>
      )}

      {ctoResult && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => { reset(); setPanelResult(null); }}
          className="text-muted-foreground"
        >
          {t.roleDashboards.cto.body.newAnalysis}
        </Button>
      )}
    </div>
  );
}

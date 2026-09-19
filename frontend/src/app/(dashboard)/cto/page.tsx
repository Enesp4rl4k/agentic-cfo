"use client";

import { useAgentJob } from "@/hooks/useAgentJob";
import { AgentJobPanel } from "@/components/ui/agent-job-panel";
import { ProactiveActionCards } from "@/components/ui/proactive-actions";
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { healthColor, healthLabel, type CTOResult } from "@/components/cto/types";
import { GitHubConnectorCard } from "@/components/cto/GitHubConnectorCard";
import { DomainPanel } from "@/components/domains/DomainPanel";
import { useCompanyContextStore } from "@/store/companyContext";
import {
  InfraSection,
  TechDebtSection,
  IncidentSection,
  VelocitySection,
} from "@/components/cto/CTOSections";

// ── Input field definitions ────────────────────────────────────────────────────

const INPUT_FIELDS = [
  { label: "Cloud Billing CSV",        key: "cloud_billing_csv", placeholder: "service,cost,date\nEC2,1234.56,2024-06" },
  { label: "Git Log (git log --stat)", key: "git_log_text",      placeholder: "commit abc1234\nAuthor: dev@company.com\n..." },
  { label: "Incident CSV",             key: "incident_csv",      placeholder: "id,severity,service,started_at,resolved_at\n1,critical,api,2024-06-01T10:00:00Z,2024-06-01T14:00:00Z" },
  { label: "Sprint CSV",               key: "sprint_csv",        placeholder: "sprint_name,planned_points,completed_points\nSprint 1,40,36" },
] as const;

// ── Input form ─────────────────────────────────────────────────────────────────

function CTOInputForm({
  onEnqueue,
  disabled,
}: {
  onEnqueue: (data: Record<string, string>) => void;
  disabled?: boolean;
}) {
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
        En az bir veri kaynağı yapıştırın. Tüm alanlar isteğe bağlıdır — agentlar eksik girdileri atlar.
      </p>
      {INPUT_FIELDS.map(({ label, key, placeholder }) => (
        <div key={key} className="space-y-1.5">
          <Label htmlFor={`cto-${key}`}>{label}</Label>
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
        {disabled ? "Analiz yapılıyor…" : "CTO Analizini Başlat"}
      </Button>
    </form>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function CTODashboardPage() {
  const { enqueue, status, progress, logs, error, result, isDone, isActive, reset } =
    useAgentJob("cto");

  // One engine: the CTO orchestrator, on files attached to the job (panel) or
  // pasted below. Nothing is shown that was not computed from real input.
  const { activeCFOJobId } = useCompanyContextStore();
  const [panelResult, setPanelResult] = useState<CTOResult | null>(null);
  const [panelKey, setPanelKey] = useState(0);

  const ctoResult: CTOResult | null =
    isDone && result ? (result as unknown as CTOResult) : panelResult;

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight">CTO Dashboard</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Altyapı maliyeti · Teknik borç · Olaylar · Geliştirme hızı
        </p>
      </div>

      <DomainPanel
        key={panelKey}
        alan="cto"
        jobId={activeCFOJobId}
        onResult={(r) => setPanelResult(r as unknown as CTOResult)}
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
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Technology Health Score</h3>
            <span className={`text-2xl font-bold tabular-nums ${healthColor(ctoResult.cto_summary.overall_health_score)}`}>
              {ctoResult.cto_summary.overall_health_score.toFixed(1)}/10
              <span className="ml-2 text-sm font-normal">
                {healthLabel(ctoResult.cto_summary.overall_health_score)}
              </span>
            </span>
          </div>

          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Object.entries(ctoResult.cto_summary.component_scores).map(([domain, score]) => (
              <div key={domain} className="text-center">
                <p className="text-[10px] uppercase text-muted-foreground">
                  {domain.replace("_", " ")}
                </p>
                <p className={`text-base font-bold ${healthColor(score as number)}`}>
                  {(score as number).toFixed(1)}
                </p>
              </div>
            ))}
          </div>

          {ctoResult.cto_summary.quick_wins.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">QUICK WINS</p>
              <div className="space-y-1.5">
                {ctoResult.cto_summary.quick_wins.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-[10px] font-bold text-emerald-400">
                      {i + 1}
                    </span>
                    <div>
                      <span className="text-foreground">{w.action}</span>
                      <span className="ml-2 text-emerald-400">{w.estimated_impact}</span>
                      <span className="ml-2 text-muted-foreground">· {w.effort} effort</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

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
          {ctoResult.infra     && <InfraSection    data={ctoResult.infra}     />}
          {ctoResult.tech_debt && <TechDebtSection data={ctoResult.tech_debt} />}
          {ctoResult.incidents && <IncidentSection data={ctoResult.incidents} />}
          {ctoResult.velocity  && <VelocitySection data={ctoResult.velocity}  />}
          {!ctoResult.infra && !ctoResult.tech_debt && !ctoResult.incidents && !ctoResult.velocity && (
            <p className="text-sm text-muted-foreground">
              Veri bulunamadı. Girdi formatını kontrol edin.
            </p>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card p-6">
          <h3 className="mb-4 text-sm font-semibold">CTO Analizi Başlat</h3>
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
          ← Yeni analiz yap
        </Button>
      )}
    </div>
  );
}

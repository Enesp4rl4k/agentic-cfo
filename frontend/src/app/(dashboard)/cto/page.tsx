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
import { HydrationHint } from "@/components/ui/hydration-hint";
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

const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// Demo mode: one click fills all four fields with the golden prefill's inputs.
// backend/scripts/demo_prefill.py mirrors these literals byte-for-byte —
// tests/test_demo_prefill_cto_inputs.py locks the mirror.
const SAMPLE_CTO_INPUTS: Record<(typeof INPUT_FIELDS)[number]["key"], string> = {
  cloud_billing_csv: `service,cost,date,description
Amazon EC2,4820.50,2024-11,prod api cluster
Amazon EC2,1975.20,2024-11,prod worker nodes
Amazon RDS,2640.00,2024-11,prod postgres primary
Amazon S3,762.40,2024-11,prod asset storage
AWS Lambda,548.30,2024-11,prod event handlers
Amazon CloudFront,431.10,2024-11,prod cdn
Amazon ElastiCache,615.75,2024-11,prod redis session cache
Amazon EC2,4610.00,2024-10,prod api cluster
Amazon RDS,2585.00,2024-10,prod postgres primary
Amazon S3,740.00,2024-10,prod asset storage
Amazon EC2,1890.00,2024-10,prod worker nodes
Staging Sandbox,185.00,2024-11,staging qa environment`,
  git_log_text: `commit 8f3a1c2b9d4e5f6a7b8c9d0e1f2a3b4c5d6e7f80
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Thu Nov 21 10:14:32 2024 +0300

    fix(billing): invoice rounding on split payments

 src/billing/invoice_service.py | 42 ++++++++++++++++++++++++---------
 src/billing/rounding.py        | 18 ++++++------
 2 files changed, 35 insertions(+), 25 deletions(-)

commit 1a9e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1908
Author: Murat Kaya <murat.kaya@tiger.com.tr>
Date:   Tue Nov 19 16:02:11 2024 +0300

    perf(api): cache rate lookups in payments endpoint

 src/api/rates_endpoint.py | 61 ++++++++++++++++++++++++++++++++++++++++------
 src/core/cache.py         | 14 +++++------
 2 files changed, 50 insertions(+), 25 deletions(-)

commit 5c2f8a1b3e4d5f6a7b8c9d0e1f2a3b4c5d6e7f11
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Mon Nov 18 09:41:07 2024 +0300

    fix(core): ledger double-post on retried jobs

 src/core/ledger.py | 27 ++++++++++++++---------------
 1 file changed, 13 insertions(+), 14 deletions(-)

commit 3e7b2c9d4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b90
Author: Kaan Yilmaz <kaan.yilmaz@tiger.com.tr>
Date:   Fri Nov 15 14:27:55 2024 +0300

    feat(checkout): retry card3ds challenge on timeout

 src/web/checkout.js | 88 ++++++++++++++++++++++++++++++++++++++-----------
 1 file changed, 64 insertions(+), 24 deletions(-)

commit 7b4d1e2f3a4c5b6d7e8f9a0b1c2d3e4f5a6b7c8d
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Wed Nov 13 11:08:19 2024 +0300

    refactor(billing): extract invoice line proration

 src/billing/invoice_service.py | 96 +++++++++++++++++++++-----------------
 src/billing/proration.py       | 47 ++++++++++++++++++
 2 files changed, 72 insertions(+), 71 deletions(-)

commit 9c5e2f3a4b5d6c7e8f9a0b1c2d3e4f5a6b7c8d9e
Author: Murat Kaya <murat.kaya@tiger.com.tr>
Date:   Mon Nov 11 17:53:42 2024 +0300

    fix(api): rates endpoint pagination overflow

 src/api/rates_endpoint.py | 22 ++++++++--------
 1 file changed, 11 insertions(+), 11 deletions(-)

commit 2d6a3b4c5e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Thu Nov 07 08:36:24 2024 +0300

    fix(core): ledger idempotency key length

 src/core/ledger.py | 19 ++++++++++--------
 1 file changed, 10 insertions(+), 9 deletions(-)

commit 4f8b5c6d7e8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c
Author: Kaan Yilmaz <kaan.yilmaz@tiger.com.tr>
Date:   Tue Nov 05 13:19:08 2024 +0300

    chore(ci): pin runner image to ubuntu-22.04

 infra/docker-compose.yml | 6 ++---
 1 file changed, 3 insertions(+), 3 deletions(-)

commit 6a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Fri Nov 01 10:02:51 2024 +0300

    feat(billing): proration rules for mid-cycle upgrades

 src/billing/invoice_service.py | 74 ++++++++++++++++++++++++-----------
 src/billing/proration.py       | 63 +++++++++++++++++++++
 2 files changed, 110 insertions(+), 27 deletions(-)

commit 8b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1
Author: Murat Kaya <murat.kaya@tiger.com.tr>
Date:   Wed Oct 30 15:44:36 2024 +0300

    perf(api): batch rate imports

 src/api/rates_endpoint.py | 35 +++++++++++++--------
 1 file changed, 21 insertions(+), 14 deletions(-)

commit 1c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Mon Oct 28 09:12:03 2024 +0300

    fix(core): stale read after ledger write

 src/core/ledger.py | 31 ++++++++++++++-----------
 1 file changed, 17 insertions(+), 14 deletions(-)

commit 5e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Tue Oct 22 16:30:45 2024 +0300

    fix(billing): vat rounding on refund credit notes

 src/billing/invoice_service.py | 38 +++++++++++++++++-------
 src/billing/rounding.py        | 12 +++++---
 2 files changed, 34 insertions(+), 16 deletions(-)

commit 7f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a
Author: Elif Demir <elif.demir@tiger.com.tr>
Date:   Thu Oct 17 09:58:22 2024 +0300

    fix(billing): tax credit note numbering gap

 src/billing/invoice_service.py | 29 +++++++++++++--------
 src/billing/rounding.py        |  6 ++--
 2 files changed, 19 insertions(+), 16 deletions(-)`,
  incident_csv: `id,title,severity,service,started_at,resolved_at
INC-1041,Payment webhook timeouts,high,payments-api,2024-11-12T09:14:00Z,2024-11-12T13:40:00Z
INC-1042,Database connection pool exhaustion,critical,core-api,2024-11-19T02:31:00Z,2024-11-19T05:02:00Z
INC-1043,Checkout latency spike,high,web-checkout,2024-11-25T14:05:00Z,2024-11-25T16:48:00Z
INC-1044,Staging deploy failure,low,ci-pipeline,2024-11-28T08:20:00Z,2024-11-28T09:05:00Z
INC-1045,Payment webhook timeouts,medium,payments-api,2024-12-03T11:47:00Z,2024-12-04T02:12:00Z
INC-1046,Search index corruption,medium,web-checkout,2024-12-09T17:32:00Z,2024-12-10T06:15:00Z
INC-1047,API auth token refresh loop,high,core-api,2024-12-16T07:55:00Z,2024-12-16T10:10:00Z
INC-1048,Payment webhook timeouts,high,payments-api,2024-12-22T19:26:00Z,2024-12-22T21:03:00Z`,
  sprint_csv: `sprint_name,planned_points,completed_points,start_date,carry_over
Sprint 2024-18,42,38,2024-09-30,4
Sprint 2024-19,45,44,2024-10-14,1
Sprint 2024-20,44,28,2024-10-28,13
Sprint 2024-21,46,43,2024-11-11,3
Sprint 2024-22,43,45,2024-11-25,0
Sprint 2024-23,44,40,2024-12-09,4`,
};

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
      {IS_DEMO && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setValues({ ...SAMPLE_CTO_INPUTS })}
        >
          {t.roleDashboards.cto.body.fillWithSample}
        </Button>
      )}
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
  // U2/1.5: context fetch while in flight — hint instead of a false "no
  // analysis" flash; the form is never gated on this.
  const [hydrating, setHydrating] = useState(true);

  // Hydrate from the stored result so a completed analysis is still visible on
  // revisit — matches the CMO/COO/CHRO pages (no re-run needed to see it).
  // Not cancelled on re-runs: orgId flips fetch the same snapshot (cmo/page).
  useEffect(() => {
    void (async () => {
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
      } finally {
        setHydrating(false);
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

      {hydrating && !ctoResult && <HydrationHint />}

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

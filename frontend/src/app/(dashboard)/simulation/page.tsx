"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { Zap, BarChart2, Brain, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { CascadePanel } from "@/components/simulation/CascadePanel";
import { CounterfactualPanel } from "@/components/simulation/CounterfactualPanel";
import { NLQueryPanel } from "@/components/simulation/NLQueryPanel";
import { BaselineSourceBadge } from "@/components/ui/baseline-source-badge";
import { getLiveDataStatus, type LiveDataStatus } from "@/lib/api/semantic";
import { useCompanyContextStore } from "@/store/companyContext";

type Tab = "cascade" | "counterfactual" | "nl";

const TABS = [
  {
    id:    "cascade"        as Tab,
    label: "Zincirleme Risk",
    icon:  <Zap       className="h-4 w-4" />,
    desc:  "Bir risk olayının tüm domainlere yayılımını simüle et",
  },
  {
    id:    "counterfactual" as Tab,
    label: "Aksiyon Analizi",
    icon:  <BarChart2 className="h-4 w-4" />,
    desc:  "Bir kararın CFO + CHRO + CTO + CMO etkisini gör",
  },
  {
    id:    "nl"             as Tab,
    label: "Doğal Dil",
    icon:  <Sparkles  className="h-4 w-4" />,
    desc:  "\"5 mühendis işe alırsam ne olur?\" tarzı soru sor",
  },
];

export default function SimulationPage() {
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") as Tab | null) ?? "cascade";
  const [tab, setTab] = useState<Tab>(
    TABS.some((t) => t.id === initialTab) ? initialTab : "cascade"
  );
  const { activeCFOJobId, orgId } = useCompanyContextStore();
  const [liveStatus, setLiveStatus] = useState<LiveDataStatus | null>(null);
  const cfAction = searchParams.get("action");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const live = await getLiveDataStatus();
        if (!cancelled) setLiveStatus(live);
      } catch {
        if (!cancelled) setLiveStatus(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  useEffect(() => {
    const t = searchParams.get("tab") as Tab | null;
    if (t && TABS.some((x) => x.id === t)) setTab(t);
  }, [searchParams]);

  const baselineSource =
    liveStatus?.baseline_source ??
    (liveStatus?.live_sync_enabled ? "semantic" : orgId || activeCFOJobId ? "context" : "none");

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Page header */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Brain className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Simülasyon Merkezi</h1>
          <BaselineSourceBadge source={baselineSource} />
        </div>
        <p className="text-muted-foreground">
          Ekonomik ve yönetimsel senaryoları simüle et, C-Suite etkisini analiz et.
        </p>
        {liveStatus?.golden_path_ready && (
          <p className="text-xs text-emerald-400">
            Live sync + semantic brief ready — simulations use canonical baselines.
          </p>
        )}
      </div>

      {/* Context banner */}
      {!activeCFOJobId && !orgId && !liveStatus?.live_sync_enabled && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3 text-sm text-yellow-400">
          <span className="font-medium">İpucu:</span> Şirket verisi yüklendiğinde simülasyonlar
          gerçek finansal metriklerinizi kullanır. Şimdi de örnek değerlerle çalışabilirsiniz.
        </div>
      )}

      {/* Tab selector */}
      <div className="grid grid-cols-3 gap-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex flex-col items-start gap-1 rounded-xl border p-4 text-left transition-colors",
              tab === t.id
                ? "border-primary bg-primary/10"
                : "border-border bg-card hover:border-primary/40"
            )}
          >
            <div className={cn(
              "flex items-center gap-2 font-semibold",
              tab === t.id ? "text-primary" : "text-foreground"
            )}>
              {t.icon}
              {t.label}
            </div>
            <p className="text-xs text-muted-foreground">{t.desc}</p>
          </button>
        ))}
      </div>

      {/* Active panel */}
      <div className="rounded-xl border border-border bg-card p-5">
        {tab === "cascade" && (
          <CascadePanel
            jobId={activeCFOJobId ?? undefined}
            orgId={orgId ?? undefined}
            baselineSource={baselineSource}
          />
        )}
        {tab === "counterfactual" && (
          <CounterfactualPanel
            jobId={activeCFOJobId ?? undefined}
            orgId={orgId ?? undefined}
            initialAction={cfAction ?? undefined}
          />
        )}
        {tab === "nl" && (
          <NLQueryPanel
            jobId={activeCFOJobId ?? null}
            orgId={orgId ?? null}
            baselineSource={baselineSource}
            goldenPathReady={liveStatus?.golden_path_ready ?? false}
          />
        )}
      </div>
    </div>
  );
}

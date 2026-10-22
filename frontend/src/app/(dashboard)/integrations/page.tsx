"use client";

import { Suspense, useState, useEffect } from "react";
import Link from "next/link";
import { Link2, RefreshCw, CheckCircle, AlertCircle, Clock, Trash2, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { EFaturaCard } from "@/components/integrations/EFaturaCard";
import { ParasutKarti } from "@/components/integrations/ParasutKarti";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/hooks/useI18n";
import type { MessageTree } from "@/lib/i18n";
import {
  useERPIntegrations,
  useERPSyncLogs,
  useDeleteERPIntegration,
  useLogoTigerSync,
  useMikroSync,
  statusColor,
  statusBg,
  syncStatusColor,
} from "@/hooks/useERP";
import type { ERPIntegration } from "@/lib/api/erp";

// ── Relative time helper ──────────────────────────────────────────────────────

type IntegrationsMessages = MessageTree["integrations"];

function formatRelative(
  isoString: string | null | undefined,
  ig: IntegrationsMessages,
  dateTag: string,
): string {
  if (!isoString) return ig.neverSynced;
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;
  if (isNaN(diffMs)) return isoString;

  const mins  = Math.floor(diffMs / 60_000);
  const hours = Math.floor(diffMs / 3_600_000);
  const days  = Math.floor(diffMs / 86_400_000);

  if (mins < 1)   return ig.ago.justNow;
  if (mins < 60)  return ig.ago.mins.replace("{count}", String(mins));
  if (hours < 24) return ig.ago.hours.replace("{count}", String(hours));
  if (days < 30)  return ig.ago.days.replace("{count}", String(days));

  return new Date(isoString).toLocaleDateString(dateTag);
}

function useRelativeTime(isoString: string | null | undefined): string {
  const { t, locale } = useI18n();
  const dateTag = locale === "tr" ? "tr-TR" : "en-US";
  const ig = t.integrations;
  const [label, setLabel] = useState<string>(() => formatRelative(isoString, ig, dateTag));

  useEffect(() => {
    const interval = setInterval(() => setLabel(formatRelative(isoString, ig, dateTag)), 30_000);
    return () => clearInterval(interval);
  }, [isoString, ig, dateTag]);

  return label;
}

// ── Integration card ───────────────────────────────────────────────────────────

function IntegrationCard({ integration }: { integration: ERPIntegration }) {
  const { remove, loading: removing } = useDeleteERPIntegration();
  const [confirm, setConfirm] = useState(false);
  const { t } = useI18n();
  const ig = t.integrations;

  return (
    <div className={cn("rounded-xl border p-4 space-y-3", statusBg(integration.status))}>
      <div className="flex items-start justify-between">
        <div className="space-y-0.5">
          <p className="font-semibold">{integration.display_name}</p>
          <p className="text-xs text-muted-foreground">
            {ig.providers[integration.provider]?.description ?? ""}
          </p>
        </div>
        <span className={cn("text-xs font-semibold px-2 py-0.5 rounded border", statusColor(integration.status))}>
          {integration.status}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-muted-foreground">{ig.card.lastSync}</p>
          <p className="font-mono" title={integration.last_sync_at ?? undefined}>
            {useRelativeTime(integration.last_sync_at)}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">{ig.card.lastCount}</p>
          <p className={cn("font-mono font-medium", syncStatusColor(integration.last_sync_status))}>
            {integration.last_sync_count != null
              ? ig.card.itemsCount.replace("{count}", String(integration.last_sync_count))
              : "—"}
            {integration.last_sync_status === "success" && (
              <span className="ml-1 text-emerald-400">✓</span>
            )}
            {integration.last_sync_status === "error" && (
              <span className="ml-1 text-red-400">✗</span>
            )}
          </p>
        </div>
      </div>

      {integration.last_error && (
        <p className="text-xs text-red-400 bg-red-500/10 rounded p-2">
          {integration.last_error.slice(0, 100)}
        </p>
      )}

      {integration.token_expired && (
        <p className="text-xs text-orange-400 bg-orange-500/10 rounded p-2">
          {ig.card.tokenExpired}
        </p>
      )}

      <div className="flex items-center gap-2 pt-1">
        {!confirm ? (
          <Button
            size="sm" variant="ghost"
            onClick={() => setConfirm(true)}
            className="text-muted-foreground hover:text-red-400"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        ) : (
          <Button
            size="sm" variant="destructive"
            onClick={() => remove(integration.id)}
            disabled={removing}
          >
            {ig.card.confirmRemove}
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Add integration card ──────────────────────────────────────────────────────

type ERPProvider = "logo_tiger" | "mikro";

function AddIntegrationCard({
  provider,
  onSelect,
}: {
  provider: ERPProvider;
  onSelect: (provider: ERPProvider) => void;
}) {
  const { t } = useI18n();
  const ig = t.integrations;
  return (
    <button
      onClick={() => onSelect(provider)}
      className="rounded-xl border border-dashed border-border p-4 text-left hover:border-primary/50 hover:bg-primary/5 transition-colors w-full space-y-1"
    >
      <p className="font-semibold text-sm">{ig.providers[provider]?.label ?? provider}</p>
      <p className="text-xs text-muted-foreground">{ig.providers[provider]?.description ?? ""}</p>
      <p className="text-xs text-primary">+ {ig.connect.cta}</p>
    </button>
  );
}

// ── Sync logs panel ───────────────────────────────────────────────────────────

function SyncLogsPanel() {
  const { data, isLoading } = useERPSyncLogs(undefined, 8);
  const { t, locale } = useI18n();
  const ig = t.integrations;
  const dateTag = locale === "tr" ? "tr-TR" : "en-US";
  if (isLoading) return <p className="text-sm text-muted-foreground">{ig.loading}</p>;
  // `data?.logs.length` guards `data` and then dereferences `logs` anyway —
  // an absent `logs` threw and took the page to the error boundary.
  if (!data?.logs?.length) return <p className="text-sm text-muted-foreground">{ig.file.empty}</p>;

  return (
    <div className="space-y-1.5">
      {data.logs.map((log) => (
        <div key={log.id} className="flex items-center justify-between text-xs py-1.5 border-b border-border/50 last:border-0">
          <div className="flex items-center gap-2">
            {log.status === "success" ? (
              <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
            ) : log.status === "running" ? (
              <RefreshCw className="h-3.5 w-3.5 text-blue-400 animate-spin" />
            ) : (
              <AlertCircle className="h-3.5 w-3.5 text-red-400" />
            )}
            <span className="font-medium">{ig.providers[log.provider as "parasut" | "logo_tiger" | "mikro" | "netsis"]?.label ?? log.provider}</span>
            <span className="text-muted-foreground">
              {new Date(log.started_at).toLocaleDateString(dateTag, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn("font-mono", syncStatusColor(log.status as never))}>
              {ig.card.transactions.replace("{count}", String(log.transactions_synced))}
            </span>
            {log.triggered_cfo_job_id && (
              <span className="text-primary/70 text-xs">{ig.logs.toCfo}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Logo Tiger / Mikro inline sync ────────────────────────────────────────────

function CSVUploadSync({ provider }: { provider: "logo_tiger" | "mikro" }) {
  const logoSync  = useLogoTigerSync();
  const mikroSync = useMikroSync();
  const [file, setFile] = useState<File | null>(null);
  const { t } = useI18n();
  const ig = t.integrations;

  const handleSync = () => {
    if (!file) return;
    if (provider === "logo_tiger") logoSync.sync(file);
    else mikroSync.sync(file);
  };

  // The Mikro panel used to have no sync behind its button at all.
  const result = provider === "logo_tiger" ? logoSync.result : mikroSync.result;
  const loading = provider === "logo_tiger" ? logoSync.loading : mikroSync.loading;

  return (
    <div className="space-y-3">
      <div className="rounded-lg border-2 border-dashed border-border p-4 text-center">
        <input
          type="file" accept=".csv,.xls,.xlsx" id={`file-${provider}`}
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <label htmlFor={`file-${provider}`} className="cursor-pointer">
          <p className="text-sm text-muted-foreground">
            {file ? file.name : ig.file.dropHint}
          </p>
          <p className="text-xs text-muted-foreground mt-1">{ig.file.logoHint}</p>
        </label>
      </div>
      <Button onClick={handleSync} disabled={!file || loading} className="w-full" size="sm">
        <Zap className={cn("h-3.5 w-3.5 mr-1", loading && "animate-pulse")} />
        {loading ? ig.file.processing : ig.file.submit}
      </Button>
      {result && (
        <div className={cn("rounded-lg border p-3 text-sm",
          result.ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-red-500/30 bg-red-500/10 text-red-400"
        )}>
          {result.ok
            ? `✓ ${(result.cfo_job_id ? ig.file.successStarted : ig.file.success).replace("{count}", String(result.sync_count))}`
            : result.error}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type ActivePanel = "logo_tiger" | "mikro" | null;

export default function IntegrationsPage() {
  const { data, isLoading, refetch } = useERPIntegrations();
  const [activePanel, setActivePanel] = useState<ActivePanel>(null);
  const { t } = useI18n();
  const ig = t.integrations;

  // Paraşüt has its own card: one button, no developer keys.
  const integrations = (data?.integrations ?? []).filter((i) => i.provider !== "parasut");
  const activeProviders = new Set(integrations.map((i) => i.provider));

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link2 className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{ig.title}</h1>
            <p className="text-sm text-muted-foreground">
              {ig.subtitle}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* The way in for most people: export a list, drop it, done. */}
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <h2 className="text-sm font-semibold">{ig.connect.heading}</h2>
          <p className="text-xs text-muted-foreground">
            {ig.connect.subtitle}
          </p>
        </div>
        <Button asChild size="sm">
          <Link href="/baglan">{ig.connect.cta}</Link>
        </Button>
      </Card>

      {/* Mevcut entegrasyonlar */}
      {isLoading ? (
        <p className="text-sm text-muted-foreground">{ig.loading}</p>
      ) : integrations.length > 0 ? (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            {ig.connected}
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {integrations.map((i) => (
              <IntegrationCard key={i.id} integration={i} />
            ))}
          </div>
        </div>
      ) : null}

      {/* Yeni entegrasyon ekle */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          {ig.addHeading}
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {(["logo_tiger", "mikro"] as const).map((p) => (
            !activeProviders.has(p) && (
              <AddIntegrationCard key={p} provider={p} onSelect={setActivePanel} />
            )
          ))}
          {activeProviders.has("logo_tiger") && activeProviders.has("mikro") && (
            <p className="text-sm text-muted-foreground col-span-3 text-center py-4">
              {ig.allConnected}
            </p>
          )}
        </div>
      </div>

      {/* GİB e-Fatura — the one connector that brings a real company's real
          invoices in. It had endpoints and no surface. */}
      <Suspense fallback={null}>
        <ParasutKarti />
      </Suspense>

      <EFaturaCard />

      {/* Aktif panel */}
      {activePanel === "logo_tiger" && (
        <Card className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">{ig.erp.logoTiger}</h3>
            <button onClick={() => setActivePanel(null)} className="text-xs text-muted-foreground">✕</button>
          </div>
          <CSVUploadSync provider="logo_tiger" />
        </Card>
      )}

      {activePanel === "mikro" && (
        <Card className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">{ig.erp.mikro}</h3>
            <button onClick={() => setActivePanel(null)} className="text-xs text-muted-foreground">✕</button>
          </div>
          <CSVUploadSync provider="mikro" />
        </Card>
      )}

      {/* Sync history */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          {ig.logs.historyHeading}
        </h2>
        <Card className="p-4">
          <SyncLogsPanel />
        </Card>
      </div>
    </div>
  );
}

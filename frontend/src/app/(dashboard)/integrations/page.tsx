"use client";

import { useState, useEffect } from "react";
import { Link2, RefreshCw, CheckCircle, AlertCircle, Clock, Trash2, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { EFaturaCard } from "@/components/integrations/EFaturaCard";
import { Button } from "@/components/ui/button";
import {
  useERPIntegrations,
  useERPSyncLogs,
  useDeleteERPIntegration,
  useParasutSync,
  useLogoTigerSync,
  ERP_PROVIDER_LABELS,
  ERP_PROVIDER_DESCRIPTIONS,
  statusColor,
  statusBg,
  syncStatusColor,
} from "@/hooks/useERP";
import type { ERPIntegration } from "@/lib/api/erp";

// ── Relative time helper ──────────────────────────────────────────────────────

function useRelativeTime(isoString: string | null | undefined): string {
  const [label, setLabel] = useState<string>(() => formatRelative(isoString));

  useEffect(() => {
    const interval = setInterval(() => setLabel(formatRelative(isoString)), 30_000);
    return () => clearInterval(interval);
  }, [isoString]);

  return label;
}

function formatRelative(isoString: string | null | undefined): string {
  if (!isoString) return "Hiç sync edilmedi";
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;
  if (isNaN(diffMs)) return isoString;

  const mins  = Math.floor(diffMs / 60_000);
  const hours = Math.floor(diffMs / 3_600_000);
  const days  = Math.floor(diffMs / 86_400_000);

  if (mins < 1)   return "Az önce";
  if (mins < 60)  return `${mins} dk önce`;
  if (hours < 24) return `${hours} saat önce`;
  if (days < 30)  return `${days} gün önce`;

  return new Date(isoString).toLocaleDateString("tr-TR");
}

// ── Integration card ───────────────────────────────────────────────────────────

function IntegrationCard({ integration }: { integration: ERPIntegration }) {
  const { remove, loading: removing } = useDeleteERPIntegration();
  const parasutSync = useParasutSync();
  const [confirm, setConfirm] = useState(false);

  const handleSync = () => {
    if (integration.provider === "parasut") {
      parasutSync.sync(integration.id);
    }
  };

  return (
    <div className={cn("rounded-xl border p-4 space-y-3", statusBg(integration.status))}>
      <div className="flex items-start justify-between">
        <div className="space-y-0.5">
          <p className="font-semibold">{integration.display_name}</p>
          <p className="text-xs text-muted-foreground">
            {ERP_PROVIDER_DESCRIPTIONS[integration.provider]}
          </p>
        </div>
        <span className={cn("text-xs font-semibold px-2 py-0.5 rounded border", statusColor(integration.status))}>
          {integration.status}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-muted-foreground">Son Sync</p>
          <p className="font-mono" title={integration.last_sync_at ?? undefined}>
            {useRelativeTime(integration.last_sync_at)}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">Son İşlem Sayısı</p>
          <p className={cn("font-mono font-medium", syncStatusColor(integration.last_sync_status))}>
            {integration.last_sync_count != null
              ? `${integration.last_sync_count} adet`
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
          OAuth token süresi doldu — yeniden bağlanın
        </p>
      )}

      <div className="flex items-center gap-2 pt-1">
        {integration.provider === "parasut" && integration.status === "active" && (
          <Button
            size="sm" variant="outline"
            onClick={handleSync}
            disabled={parasutSync.loading}
            className="flex-1"
          >
            <RefreshCw className={cn("h-3.5 w-3.5 mr-1", parasutSync.loading && "animate-spin")} />
            Sync
          </Button>
        )}
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
            Sil?
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Add integration card ──────────────────────────────────────────────────────

type ERPProvider = "parasut" | "logo_tiger" | "mikro";

function AddIntegrationCard({
  provider,
  onSelect,
}: {
  provider: ERPProvider;
  onSelect: (provider: ERPProvider) => void;
}) {
  return (
    <button
      onClick={() => onSelect(provider)}
      className="rounded-xl border border-dashed border-border p-4 text-left hover:border-primary/50 hover:bg-primary/5 transition-colors w-full space-y-1"
    >
      <p className="font-semibold text-sm">{ERP_PROVIDER_LABELS[provider]}</p>
      <p className="text-xs text-muted-foreground">{ERP_PROVIDER_DESCRIPTIONS[provider]}</p>
      <p className="text-xs text-primary">+ Bağlan</p>
    </button>
  );
}

// ── Sync logs panel ───────────────────────────────────────────────────────────

function SyncLogsPanel() {
  const { data, isLoading } = useERPSyncLogs(undefined, 8);
  if (isLoading) return <p className="text-sm text-muted-foreground">Yükleniyor...</p>;
  // `data?.logs.length` guards `data` and then dereferences `logs` anyway —
  // an absent `logs` threw and took the page to the error boundary.
  if (!data?.logs?.length) return <p className="text-sm text-muted-foreground">Henüz sync yapılmadı.</p>;

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
            <span className="font-medium">{ERP_PROVIDER_LABELS[log.provider as "parasut" | "logo_tiger" | "mikro" | "netsis"]}</span>
            <span className="text-muted-foreground">
              {new Date(log.started_at).toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn("font-mono", syncStatusColor(log.status as never))}>
              {log.transactions_synced} işlem
            </span>
            {log.triggered_cfo_job_id && (
              <span className="text-primary/70 text-xs">→ CFO</span>
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
  const [file, setFile] = useState<File | null>(null);

  const handleSync = () => {
    if (!file) return;
    if (provider === "logo_tiger") logoSync.sync(file);
  };

  const result = provider === "logo_tiger" ? logoSync.result : null;
  const loading = provider === "logo_tiger" ? logoSync.loading : false;

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
            {file ? file.name : "CSV dosyasını sürükle veya seç"}
          </p>
          <p className="text-xs text-muted-foreground mt-1">Logo Tiger: Fiş Listesi, Hesap Hareketleri</p>
        </label>
      </div>
      <Button onClick={handleSync} disabled={!file || loading} className="w-full" size="sm">
        <Zap className={cn("h-3.5 w-3.5 mr-1", loading && "animate-pulse")} />
        {loading ? "İşleniyor..." : "Yükle ve CFO Analizini Başlat"}
      </Button>
      {result && (
        <div className={cn("rounded-lg border p-3 text-sm",
          result.ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-red-500/30 bg-red-500/10 text-red-400"
        )}>
          {result.ok
            ? `✓ ${result.sync_count} işlem sync edildi${result.cfo_job_id ? " — CFO analizi başlatıldı" : ""}`
            : result.error}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type ActivePanel = "parasut" | "logo_tiger" | "mikro" | null;

export default function IntegrationsPage() {
  const { data, isLoading, refetch } = useERPIntegrations();
  const [activePanel, setActivePanel] = useState<ActivePanel>(null);

  const integrations = data?.integrations ?? [];
  const activeProviders = new Set(integrations.map((i) => i.provider));

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link2 className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Integrations</h1>
            <p className="text-sm text-muted-foreground">
              Core connectors (CSV / generic) vs Turkey pack (Paraşüt, Logo, e-Fatura)
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* Core vs Turkey pack */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Card className="p-4 space-y-1">
          <h2 className="text-sm font-semibold">Core connectors</h2>
          <p className="text-xs text-muted-foreground">
            Upload CSV/XLSX/PDF on the Upload page. QuickBooks/Xero CSV maps are documented in INTERNATIONAL_PLATFORM.md (OAuth later).
          </p>
        </Card>
        <Card className="p-4 space-y-1">
          <h2 className="text-sm font-semibold">Turkey pack</h2>
          <p className="text-xs text-muted-foreground">
            Paraşüt, Logo Tiger, Mikro, GİB e-Fatura — enable via org regional_packs includes &quot;tr&quot;.
          </p>
        </Card>
      </div>

      {/* Mevcut entegrasyonlar */}
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Yükleniyor...</p>
      ) : integrations.length > 0 ? (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            Bağlı Entegrasyonlar
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
          Entegrasyon Ekle
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {(["parasut", "logo_tiger", "mikro"] as const).map((p) => (
            !activeProviders.has(p) && (
              <AddIntegrationCard key={p} provider={p} onSelect={setActivePanel} />
            )
          ))}
          {activeProviders.size === 3 && (
            <p className="text-sm text-muted-foreground col-span-3 text-center py-4">
              Tüm desteklenen entegrasyonlar bağlı.
            </p>
          )}
        </div>
      </div>

      {/* GİB e-Fatura — the one connector that brings a real company's real
          invoices in. It had endpoints and no surface. */}
      <EFaturaCard />

      {/* Aktif panel */}
      {activePanel === "logo_tiger" && (
        <Card className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">Logo Tiger CSV Sync</h3>
            <button onClick={() => setActivePanel(null)} className="text-xs text-muted-foreground">✕</button>
          </div>
          <CSVUploadSync provider="logo_tiger" />
        </Card>
      )}

      {activePanel === "mikro" && (
        <Card className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">Mikro ERP CSV Sync</h3>
            <button onClick={() => setActivePanel(null)} className="text-xs text-muted-foreground">✕</button>
          </div>
          <CSVUploadSync provider="mikro" />
        </Card>
      )}

      {activePanel === "parasut" && (
        <Card className="p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">Paraşüt OAuth2 Bağlantısı</h3>
            <button onClick={() => setActivePanel(null)} className="text-xs text-muted-foreground">✕</button>
          </div>
          <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3 text-sm space-y-2">
            <p className="font-medium text-blue-400">Nasıl bağlanılır?</p>
            <ol className="list-decimal list-inside space-y-1 text-xs text-muted-foreground">
              <li>Paraşüt'te Ayarlar → Uygulama → Yeni Uygulama oluşturun</li>
              <li>Client ID ve Client Secret kopyalayın</li>
              <li>Callback URL: <code className="text-primary">{typeof window !== "undefined" ? window.location.origin : ""}/erp/parasut/callback</code></li>
              <li>Aşağıdaki formu doldurun ve "Bağlan" butonuna tıklayın</li>
            </ol>
          </div>
          <ParasutConnectForm onClose={() => setActivePanel(null)} />
        </Card>
      )}

      {/* Sync history */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Sync Geçmişi
        </h2>
        <Card className="p-4">
          <SyncLogsPanel />
        </Card>
      </div>
    </div>
  );
}

// ── Paraşüt connect form ──────────────────────────────────────────────────────

function ParasutConnectForm({ onClose }: { onClose: () => void }) {
  const [clientId, setClientId]     = useState("");
  const [secret, setSecret]         = useState("");
  const [companyId, setCompanyId]   = useState("");
  const [result, setResult]         = useState<{ auth_url: string } | null>(null);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);

  const handleConnect = async () => {
    if (!clientId || !secret || !companyId) return;
    setLoading(true);
    setError(null);
    try {
      const { connectParasut } = await import("@/lib/api/erp");
      const res = await connectParasut({
        client_id:     clientId,
        client_secret: secret,
        company_id:    companyId,
        redirect_uri:  `${window.location.origin}/erp/parasut/callback`,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bağlantı başarısız");
    } finally {
      setLoading(false);
    }
  };

  if (result?.auth_url) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-emerald-400">✓ Paraşüt yetkilendirme URL'i oluşturuldu.</p>
        <Button asChild className="w-full">
          <a href={result.auth_url} target="_blank" rel="noreferrer">
            Paraşüt'te Yetkilendir →
          </a>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {[
        { label: "Client ID",     value: clientId,   set: setClientId,   ph: "parasut_client_id_..." },
        { label: "Client Secret", value: secret,     set: setSecret,     ph: "••••••••••••" },
        { label: "Firma ID",      value: companyId,  set: setCompanyId,  ph: "123456" },
      ].map(({ label, value, set, ph }) => (
        <div key={label} className="space-y-1">
          <label className="text-xs text-muted-foreground">{label}</label>
          <input
            type={label === "Client Secret" ? "password" : "text"}
            value={value}
            onChange={(e) => set(e.target.value)}
            placeholder={ph}
            className="w-full rounded-md border border-border bg-card px-3 py-1.5 text-sm"
          />
        </div>
      ))}
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex gap-2">
        <Button onClick={handleConnect} disabled={loading || !clientId || !secret || !companyId} className="flex-1">
          {loading ? "Bağlanıyor..." : "Bağlan"}
        </Button>
        <Button variant="outline" onClick={onClose}>İptal</Button>
      </div>
    </div>
  );
}

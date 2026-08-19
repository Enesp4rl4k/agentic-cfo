"use client";

export const dynamic = "force-dynamic";

import { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2, XCircle, Edit3, RefreshCw, ChevronDown, ChevronUp,
  AlertTriangle, Clock, FileText, TrendingUp, Users, Filter,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

// ── Types ──────────────────────────────────────────────────────────────────────

interface OnayKaydi {
  id:                      string;
  job_id:                  string;
  kayit_id:                string;
  durum:                   "bekliyor" | "onaylandi" | "duzeltildi" | "reddedildi";
  tx_description:          string | null;
  tx_amount_try:           number | null;
  tx_tarih:                string | null;
  otomatik_hesap_kodu:     string | null;
  otomatik_confidence:     number | null;
  otomatik_yontem:         string | null;
  onay_neden:              string | null;
  duzeltilmis_hesap_kodu:  string | null;
  duzeltilmis_hesap_adi:   string | null;
  onaylayan_user_id:       string | null;
  onay_zamani:             string | null;
  onay_notu:               string | null;
  orijinal_kayit:          Record<string, unknown> | null;
  created_at:              string;
}

interface OnayStats {
  bekliyor:    number;
  onaylandi:   number;
  duzeltildi:  number;
  reddedildi:  number;
  toplam:      number;
  avg_confidence: number | null;
  onay_orani:  number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function confidenceColor(c: number | null): string {
  if (c === null) return "text-muted-foreground";
  if (c >= 0.8)  return "text-emerald-400";
  if (c >= 0.6)  return "text-yellow-400";
  return "text-red-400";
}

function durumBadge(durum: string) {
  const cfg: Record<string, { label: string; color: string }> = {
    bekliyor:   { label: "Bekliyor",   color: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20" },
    onaylandi:  { label: "Onaylandı",  color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
    duzeltildi: { label: "Düzeltildi", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
    reddedildi: { label: "Reddedildi", color: "bg-red-500/10 text-red-400 border-red-500/20" },
  };
  const c = cfg[durum] ?? { label: durum, color: "bg-muted text-muted-foreground border-border" };
  return (
    <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold", c.color)}>
      {c.label}
    </span>
  );
}

function fmtAmount(v: number | null): string {
  if (v === null) return "—";
  return `₺${v.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}`;
}

function fmtDate(d: string | null): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("tr-TR", { day: "2-digit", month: "short", year: "numeric" });
}

// ── Düzeltme modal ────────────────────────────────────────────────────────────

function DuzelModal({
  kayit, onClose, onSuccess,
}: { kayit: OnayKaydi; onClose: () => void; onSuccess: () => void }) {
  const [hesapKodu, setHesapKodu] = useState(kayit.otomatik_hesap_kodu ?? "");
  const [hesapAdi,  setHesapAdi]  = useState("");
  const [aciklama,  setAciklama]  = useState("");
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!hesapKodu.trim()) { setError("Hesap kodu zorunlu"); return; }
    if (!hesapAdi.trim())  { setError("Hesap adı zorunlu"); return; }
    setLoading(true); setError(null);
    try {
      await apiClient.post(`/smmm/onay/${kayit.id}/duzeltle`, {
        hesap_kodu: hesapKodu,
        hesap_adi:  hesapAdi,
        aciklama:   aciklama || null,
      });
      onSuccess();
    } catch {
      setError("Düzeltme kaydedilemedi");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-md p-5 space-y-4">
        <h3 className="font-semibold">Hesap Kodu Düzeltme</h3>
        <div className="text-xs text-muted-foreground bg-muted/30 rounded p-2">
          <p className="truncate">{kayit.tx_description ?? "—"}</p>
          <p className="font-mono mt-0.5">{fmtAmount(kayit.tx_amount_try)}</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Hesap Kodu *</label>
            <input type="text" value={hesapKodu}
              onChange={(e) => setHesapKodu(e.target.value)}
              placeholder="örn: 320"
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring font-mono"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Hesap Adı *</label>
            <input type="text" value={hesapAdi}
              onChange={(e) => setHesapAdi(e.target.value)}
              placeholder="örn: Satıcılar"
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Gerekçe (opsiyonel)</label>
            <textarea value={aciklama} rows={2}
              onChange={(e) => setAciklama(e.target.value)}
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2 justify-end pt-1">
            <Button type="button" variant="outline" onClick={onClose}>İptal</Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Kaydediliyor…" : "Düzeltmeyi Kaydet"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

// ── Red modal ─────────────────────────────────────────────────────────────────

function RedModal({
  kayit, onClose, onSuccess,
}: { kayit: OnayKaydi; onClose: () => void; onSuccess: () => void }) {
  const [neden,   setNeden]   = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!neden.trim()) { setError("Red gerekçesi zorunlu"); return; }
    setLoading(true); setError(null);
    try {
      await apiClient.post(`/smmm/onay/${kayit.id}/reddet`, { neden });
      onSuccess();
    } catch {
      setError("Red işlemi gerçekleştirilemedi");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-sm p-5 space-y-4">
        <h3 className="font-semibold text-red-400">Kaydı Reddet</h3>
        <p className="text-xs text-muted-foreground truncate">{kayit.tx_description ?? "—"}</p>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Red Gerekçesi *</label>
            <textarea value={neden} rows={3}
              onChange={(e) => setNeden(e.target.value)}
              placeholder="Neden reddedildi?"
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="outline" onClick={onClose}>İptal</Button>
            <Button type="submit" variant="destructive" disabled={loading}>
              {loading ? "İşleniyor…" : "Reddet"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

// ── Onay card ─────────────────────────────────────────────────────────────────

function OnayCard({
  kayit, selected, onSelect, onRefresh,
}: {
  kayit:     OnayKaydi;
  selected:  boolean;
  onSelect:  (id: string, checked: boolean) => void;
  onRefresh: () => void;
}) {
  const [expanded,    setExpanded]    = useState(false);
  const [showDuzel,   setShowDuzel]   = useState(false);
  const [showReddet,  setShowReddet]  = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  async function handleOnayla() {
    setActionLoading(true);
    try {
      await apiClient.post(`/smmm/onay/${kayit.id}/onayla`, {});
      onRefresh();
    } catch {
      // silently fail for now
    } finally {
      setActionLoading(false);
    }
  }

  const isBekliyor = kayit.durum === "bekliyor";

  return (
    <>
      <div className={cn(
        "rounded-lg border transition-colors",
        isBekliyor ? "border-border bg-card" : "border-border/50 bg-muted/10",
        selected && "border-primary/50 bg-primary/5"
      )}>
        <div className="flex items-start gap-3 p-3">
          {/* Checkbox (only for bekliyor) */}
          {isBekliyor && (
            <input type="checkbox" checked={selected}
              onChange={(e) => onSelect(kayit.id, e.target.checked)}
              className="mt-1 h-3.5 w-3.5 rounded border-border"
              aria-label={`${kayit.tx_description} seç`}
            />
          )}

          {/* Main content */}
          <div className="flex-1 min-w-0 space-y-1.5">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <p className="text-sm font-medium truncate">{kayit.tx_description ?? "İşlem açıklaması yok"}</p>
              {durumBadge(kayit.durum)}
            </div>

            <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
              <span className="font-mono font-semibold text-foreground">{fmtAmount(kayit.tx_amount_try)}</span>
              <span>{fmtDate(kayit.tx_tarih)}</span>
              {kayit.otomatik_hesap_kodu && (
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                  {kayit.otomatik_hesap_kodu}
                  {kayit.duzeltilmis_hesap_kodu && kayit.duzeltilmis_hesap_kodu !== kayit.otomatik_hesap_kodu && (
                    <> → <span className="text-blue-400">{kayit.duzeltilmis_hesap_kodu}</span></>
                  )}
                </span>
              )}
              {kayit.otomatik_confidence !== null && (
                <span className={cn("font-semibold", confidenceColor(kayit.otomatik_confidence))}>
                  %{Math.round((kayit.otomatik_confidence ?? 0) * 100)} güven
                </span>
              )}
            </div>

            {/* Onay neden */}
            {kayit.onay_neden && (
              <p className="text-[11px] text-orange-400 border border-orange-500/20 bg-orange-500/5 rounded px-2 py-1">
                ⚠ {kayit.onay_neden}
              </p>
            )}

            {/* Expandable details */}
            {kayit.orijinal_kayit && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
              >
                {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {expanded ? "Detayı Gizle" : "Orijinal Kaydı Gör"}
              </button>
            )}
            {expanded && kayit.orijinal_kayit && (
              <pre className="rounded bg-muted/30 p-2 text-[10px] font-mono overflow-x-auto max-h-32">
                {JSON.stringify(kayit.orijinal_kayit, null, 2)}
              </pre>
            )}
          </div>

          {/* Action buttons (only for bekliyor) */}
          {isBekliyor && (
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={handleOnayla}
                disabled={actionLoading}
                className="rounded p-1.5 text-emerald-400 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
                title="Onayla"
                aria-label="Onayla"
              >
                <CheckCircle2 className="h-4 w-4" />
              </button>
              <button
                onClick={() => setShowDuzel(true)}
                disabled={actionLoading}
                className="rounded p-1.5 text-blue-400 hover:bg-blue-500/10 transition-colors disabled:opacity-50"
                title="Düzelt ve Onayla"
                aria-label="Düzelt ve Onayla"
              >
                <Edit3 className="h-4 w-4" />
              </button>
              <button
                onClick={() => setShowReddet(true)}
                disabled={actionLoading}
                className="rounded p-1.5 text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                title="Reddet"
                aria-label="Reddet"
              >
                <XCircle className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>

      {showDuzel && (
        <DuzelModal kayit={kayit} onClose={() => setShowDuzel(false)} onSuccess={() => { setShowDuzel(false); onRefresh(); }} />
      )}
      {showReddet && (
        <RedModal kayit={kayit} onClose={() => setShowReddet(false)} onSuccess={() => { setShowReddet(false); onRefresh(); }} />
      )}
    </>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function SMMMonayPage() {
  const [kayitlar,  setKayitlar]  = useState<OnayKaydi[]>([]);
  const [stats,     setStats]     = useState<OnayStats | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [durum,     setDurum]     = useState<string>("bekliyor");
  const [selected,  setSelected]  = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [qRes, sRes] = await Promise.all([
        apiClient.get<{ data: { kayitlar: OnayKaydi[] } }>(`/smmm/onay/queue?durum=${durum}&limit=100`),
        apiClient.get<{ data: OnayStats }>("/smmm/onay/stats"),
      ]);
      setKayitlar(qRes.data.data.kayitlar ?? []);
      setStats(sRes.data.data);
      setSelected(new Set());
    } catch {
      setError("Veriler yüklenemedi");
    } finally {
      setLoading(false);
    }
  }, [durum]);

  useEffect(() => { fetchData(); }, [fetchData]);

  function handleSelect(id: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }

  function handleSelectAll(checked: boolean) {
    if (checked) {
      setSelected(new Set(kayitlar.filter((k) => k.durum === "bekliyor").map((k) => k.id)));
    } else {
      setSelected(new Set());
    }
  }

  async function handleBulkApprove() {
    if (selected.size === 0) return;
    if (!confirm(`${selected.size} kaydı toplu onaylıyor musunuz?`)) return;
    setBulkLoading(true);
    try {
      await apiClient.post("/smmm/onay/toplu-onayla", { kayit_idler: Array.from(selected) });
      fetchData();
    } catch {
      setError("Toplu onay başarısız");
    } finally {
      setBulkLoading(false);
    }
  }

  const bekleyenSayisi = stats?.bekliyor ?? 0;
  const allBekliyor = kayitlar.filter((k) => k.durum === "bekliyor");

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <FileText className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">SMMM Onay Kuyruğu</h1>
            <p className="text-sm text-muted-foreground">Agent hazırlar, muhasebeci tek tıkla onaylar</p>
          </div>
          {bekleyenSayisi > 0 && (
            <span className="rounded-full bg-orange-500/15 border border-orange-500/20 px-2.5 py-0.5 text-sm font-bold text-orange-400">
              {bekleyenSayisi} bekliyor
            </span>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={loading} aria-label="Yenile">
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </Button>
      </div>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: "Bekliyor",   value: stats.bekliyor,   color: "text-yellow-400" },
            { label: "Onaylandı",  value: stats.onaylandi,  color: "text-emerald-400" },
            { label: "Düzeltildi", value: stats.duzeltildi, color: "text-blue-400" },
            { label: "Reddedildi", value: stats.reddedildi, color: "text-red-400" },
          ].map((s) => (
            <Card key={s.label} className="p-3 space-y-0.5">
              <p className="text-xs text-muted-foreground">{s.label}</p>
              <p className={cn("text-2xl font-bold tabular-nums", s.color)}>{s.value}</p>
            </Card>
          ))}
        </div>
      )}

      {/* Filter + Bulk actions */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          {["bekliyor", "onaylandi", "duzeltildi", "reddedildi", "all"].map((d) => (
            <button
              key={d}
              onClick={() => setDurum(d)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                durum === d
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:text-foreground"
              )}
            >
              {d === "all" ? "Tümü" : d === "bekliyor" ? "Bekliyor" : d === "onaylandi" ? "Onaylı" : d === "duzeltildi" ? "Düzeltildi" : "Reddedildi"}
            </button>
          ))}
        </div>

        {durum === "bekliyor" && allBekliyor.length > 0 && (
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
              <input type="checkbox"
                checked={selected.size === allBekliyor.length && allBekliyor.length > 0}
                onChange={(e) => handleSelectAll(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Tümünü Seç ({allBekliyor.length})
            </label>
            {selected.size > 0 && (
              <Button size="sm" onClick={handleBulkApprove} disabled={bulkLoading}>
                <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                {bulkLoading ? "İşleniyor…" : `${selected.size} Kaydı Toplu Onayla`}
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {/* Queue */}
      {loading && kayitlar.length === 0 ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="rounded-lg border border-border bg-card p-3 animate-pulse space-y-2">
              <div className="h-4 w-64 rounded bg-muted" />
              <div className="h-3 w-32 rounded bg-muted" />
            </div>
          ))}
        </div>
      ) : kayitlar.length === 0 ? (
        <Card className="p-12 text-center space-y-3">
          <CheckCircle2 className="h-10 w-10 text-emerald-400 mx-auto" />
          <p className="font-semibold text-emerald-400">
            {durum === "bekliyor" ? "Tüm kayıtlar onaylandı — kuyruk boş!" : "Bu filtrede kayıt yok"}
          </p>
          <p className="text-sm text-muted-foreground">
            {durum === "bekliyor"
              ? "Yeni bir analiz çalıştırıldığında düşük güvenli işlemler buraya düşer."
              : "Farklı bir filtre seçin veya analiz başlatın."}
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {kayitlar.map((kayit) => (
            <OnayCard
              key={kayit.id}
              kayit={kayit}
              selected={selected.has(kayit.id)}
              onSelect={handleSelect}
              onRefresh={fetchData}
            />
          ))}
        </div>
      )}
    </main>
  );
}

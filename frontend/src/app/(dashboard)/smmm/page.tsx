"use client";

export const dynamic = "force-dynamic";

import { useState, useEffect, useCallback } from "react";
import {
  Users, Plus, Trash2, BarChart3, RefreshCw, Building2,
  TrendingUp, AlertTriangle, CheckCircle2, ChevronRight,
  FileText, Phone, MapPin, X,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

// ── Types ──────────────────────────────────────────────────────────────────────

interface SMMMMuhasebeci {
  id:        string;
  unvan:     string | null;
  firma_adi: string | null;
  vergi_no:  string | null;
  oda_no:    string | null;
  il:        string | null;
  telefon:   string | null;
  is_active: boolean;
}

interface SMMMMusteriSummary {
  id:            string;
  firma_adi:     string;
  vergi_no:      string | null;
  sektor:        string | null;
  buyukluk:      string | null;
  il:            string | null;
  is_active:     boolean;
  health_score:  number | null;
  last_analysis: string | null;
  alert_count:   number;
}

interface SMMMMusteriCreate {
  firma_adi: string;
  vergi_no?: string;
  sektor?:   string;
  buyukluk?: string;
  il?:       string;
  notlar?:   string;
}

interface DashboardData {
  total_clients:     number;
  active_clients:    number;
  avg_health_score:  number | null;
  critical_clients:  number;
  clients:           SMMMMusteriSummary[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function healthColor(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score >= 7)  return "text-emerald-400";
  if (score >= 5)  return "text-yellow-400";
  if (score >= 3)  return "text-orange-400";
  return "text-red-400";
}

function healthBg(score: number | null): string {
  if (score === null) return "bg-muted/50";
  if (score >= 7)  return "bg-emerald-500/10 border-emerald-500/30";
  if (score >= 5)  return "bg-yellow-500/10 border-yellow-500/30";
  if (score >= 3)  return "bg-orange-500/10 border-orange-500/30";
  return "bg-red-500/10 border-red-500/30";
}

function healthLabel(score: number | null): string {
  if (score === null) return "Analiz yok";
  if (score >= 7)  return "İyi";
  if (score >= 5)  return "Orta";
  if (score >= 3)  return "Riskli";
  return "Kritik";
}

function fmt(d: string | null): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("tr-TR", { day: "2-digit", month: "short", year: "numeric" });
}

// ── Register modal ─────────────────────────────────────────────────────────────

function RegisterModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState({ unvan: "", firma_adi: "", vergi_no: "", oda_no: "", il: "", telefon: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await apiClient.post("/smmm/register", form);
      onSuccess();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Kayıt başarısız");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-lg">SMMM Kaydı</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground" aria-label="Kapat">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          {([
            ["unvan",     "Ünvan (SMMM / YMM)"],
            ["firma_adi", "Firma Adı"],
            ["vergi_no",  "Vergi No"],
            ["oda_no",    "Oda Sicil No"],
            ["il",        "İl"],
            ["telefon",   "Telefon"],
          ] as [keyof typeof form, string][]).map(([key, label]) => (
            <div key={key} className="space-y-1">
              <label className="text-xs text-muted-foreground">{label}</label>
              <input
                type="text"
                value={form[key]}
                onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          ))}
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="outline" onClick={onClose}>İptal</Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Kaydediliyor…" : "Kaydet"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

// ── Add client modal ───────────────────────────────────────────────────────────

function AddClientModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState<SMMMMusteriCreate>({
    firma_adi: "", vergi_no: "", sektor: "saas", buyukluk: "smb", il: "", notlar: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.firma_adi.trim()) { setError("Firma adı zorunlu"); return; }
    setLoading(true);
    setError(null);
    try {
      await apiClient.post("/smmm/clients", form);
      onSuccess();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Müşteri eklenemedi");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-lg">Yeni Müşteri Ekle</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground" aria-label="Kapat">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Firma Adı *</label>
            <input type="text" value={form.firma_adi}
              onChange={(e) => setForm((p) => ({ ...p, firma_adi: e.target.value }))}
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="Örn: ABC Yazılım A.Ş."
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Vergi No</label>
              <input type="text" value={form.vergi_no ?? ""}
                onChange={(e) => setForm((p) => ({ ...p, vergi_no: e.target.value }))}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">İl</label>
              <input type="text" value={form.il ?? ""}
                onChange={(e) => setForm((p) => ({ ...p, il: e.target.value }))}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder="İstanbul"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Sektör</label>
              <select value={form.sektor ?? "saas"}
                onChange={(e) => setForm((p) => ({ ...p, sektor: e.target.value }))}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring">
                {["saas", "ecommerce", "fintech", "services", "retail", "manufacturing"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Büyüklük</label>
              <select value={form.buyukluk ?? "smb"}
                onChange={(e) => setForm((p) => ({ ...p, buyukluk: e.target.value }))}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring">
                {["startup", "smb", "enterprise"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Notlar</label>
            <textarea value={form.notlar ?? ""} rows={2}
              onChange={(e) => setForm((p) => ({ ...p, notlar: e.target.value }))}
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="outline" onClick={onClose}>İptal</Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Ekleniyor…" : "Müşteri Ekle"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

// ── Client row ─────────────────────────────────────────────────────────────────

function ClientRow({
  client, onDelete, onAnalyze,
}: {
  client:    SMMMMusteriSummary;
  onDelete:  (id: string) => void;
  onAnalyze: (id: string) => void;
}) {
  return (
    <tr className="border-b border-border hover:bg-muted/20 transition-colors">
      <td className="py-3 px-3">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground shrink-0" />
          <div>
            <p className="text-sm font-medium">{client.firma_adi}</p>
            {client.vergi_no && (
              <p className="text-xs text-muted-foreground">{client.vergi_no}</p>
            )}
          </div>
        </div>
      </td>
      <td className="py-3 px-3 text-xs text-muted-foreground">
        <span className="capitalize">{client.sektor ?? "—"}</span>
        {client.buyukluk && <span className="ml-1 text-muted-foreground/60">· {client.buyukluk}</span>}
      </td>
      <td className="py-3 px-3 text-xs text-muted-foreground">
        {client.il ? (
          <span className="flex items-center gap-1">
            <MapPin className="h-3 w-3" />
            {client.il}
          </span>
        ) : "—"}
      </td>
      <td className="py-3 px-3">
        <div className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium border", healthBg(client.health_score))}>
          <span className={cn("h-1.5 w-1.5 rounded-full", client.health_score === null ? "bg-muted-foreground" : client.health_score >= 7 ? "bg-emerald-400" : client.health_score >= 5 ? "bg-yellow-400" : client.health_score >= 3 ? "bg-orange-400" : "bg-red-400")} />
          <span className={healthColor(client.health_score)}>
            {client.health_score !== null ? `${client.health_score.toFixed(1)}/10` : "—"} {healthLabel(client.health_score)}
          </span>
        </div>
      </td>
      <td className="py-3 px-3 text-xs text-muted-foreground">
        {client.alert_count > 0 ? (
          <span className="flex items-center gap-1 text-orange-400">
            <AlertTriangle className="h-3 w-3" />
            {client.alert_count} uyarı
          </span>
        ) : (
          <span className="flex items-center gap-1 text-emerald-400">
            <CheckCircle2 className="h-3 w-3" />
            Temiz
          </span>
        )}
      </td>
      <td className="py-3 px-3 text-xs text-muted-foreground">{fmt(client.last_analysis)}</td>
      <td className="py-3 px-3">
        <div className="flex items-center gap-1">
          <button
            onClick={() => onAnalyze(client.id)}
            className="rounded p-1 text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
            title="Analiz başlat"
            aria-label={`${client.firma_adi} için analiz başlat`}
          >
            <BarChart3 className="h-4 w-4" />
          </button>
          <button
            onClick={() => onDelete(client.id)}
            className="rounded p-1 text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title="Müşteri sil"
            aria-label={`${client.firma_adi} müşterisini sil`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </td>
    </tr>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function SMMMMuhasebecPage() {
  const [profile,    setProfile]    = useState<SMMMMuhasebeci | null>(null);
  const [dashboard,  setDashboard]  = useState<DashboardData | null>(null);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const [notRegistered, setNotRegistered] = useState(false);

  const [showRegister,  setShowRegister]  = useState(false);
  const [showAddClient, setShowAddClient] = useState(false);

  const [analyzeId, setAnalyzeId]   = useState<string | null>(null);
  const [analyzeMsg, setAnalyzeMsg] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [profileRes, dashRes] = await Promise.all([
        apiClient.get<SMMMMuhasebeci>("/smmm/profile"),
        apiClient.get<DashboardData>("/smmm/dashboard"),
      ]);
      setProfile(profileRes.data);
      setDashboard(dashRes.data);
      setNotRegistered(false);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        setNotRegistered(true);
      } else {
        setError("Veri yüklenemedi. Lütfen tekrar deneyin.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function handleDelete(id: string) {
    if (!confirm("Bu müşteriyi silmek istediğinizden emin misiniz?")) return;
    try {
      await apiClient.delete(`/smmm/clients/${id}`);
      fetchData();
    } catch {
      setError("Müşteri silinemedi");
    }
  }

  async function handleAnalyze(id: string) {
    setAnalyzeId(id);
    setAnalyzeMsg(null);
    try {
      const res = await apiClient.post<{ job_id?: string; message?: string }>(
        `/smmm/clients/${id}/analyze`, {}
      );
      setAnalyzeMsg(res.data.message ?? `Analiz başlatıldı (${res.data.job_id ?? ""})`);
    } catch {
      setAnalyzeMsg("Analiz başlatılamadı");
    } finally {
      setAnalyzeId(null);
    }
  }

  // ── Not registered ───────────────────────────────────────────────────────────
  if (notRegistered) {
    return (
      <main className="mx-auto max-w-screen-lg p-6 flex flex-col items-center justify-center min-h-[60vh] space-y-4">
        <div className="rounded-full bg-muted p-5">
          <Users className="h-10 w-10 text-muted-foreground" />
        </div>
        <h1 className="text-2xl font-bold">SMMM Portalı</h1>
        <p className="text-muted-foreground text-center max-w-sm">
          Bu modül muhasebeciler için. Birden fazla müşteri firmasını tek panelden yönetmek için SMMM olarak kayıt olun.
        </p>
        <Button onClick={() => setShowRegister(true)} size="lg">
          <Plus className="h-4 w-4 mr-2" />
          SMMM Olarak Kayıt Ol
        </Button>
        {showRegister && (
          <RegisterModal
            onClose={() => setShowRegister(false)}
            onSuccess={() => { setShowRegister(false); fetchData(); }}
          />
        )}
      </main>
    );
  }

  const clients = dashboard?.clients ?? [];
  const critical = clients.filter((c) => c.health_score !== null && c.health_score < 3).length;

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Users className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">SMMM Portalı</h1>
            <p className="text-sm text-muted-foreground">
              {profile?.firma_adi ?? profile?.unvan ?? "Muhasebeci Paneli"} — çoklu müşteri yönetimi
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchData} disabled={loading} aria-label="Yenile">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </Button>
          <Button size="sm" onClick={() => setShowAddClient(true)}>
            <Plus className="h-4 w-4 mr-1.5" />
            Müşteri Ekle
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Analyze feedback */}
      {analyzeMsg && (
        <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3 text-sm text-blue-400 flex items-center justify-between">
          {analyzeMsg}
          <button onClick={() => setAnalyzeMsg(null)} aria-label="Kapat"><X className="h-4 w-4" /></button>
        </div>
      )}

      {/* Summary cards */}
      {dashboard && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Card className="p-4 space-y-1">
            <p className="text-xs text-muted-foreground">Toplam Müşteri</p>
            <p className="text-2xl font-bold tabular-nums">{dashboard.total_clients}</p>
          </Card>
          <Card className="p-4 space-y-1">
            <p className="text-xs text-muted-foreground">Aktif</p>
            <p className="text-2xl font-bold tabular-nums text-emerald-400">{dashboard.active_clients}</p>
          </Card>
          <Card className="p-4 space-y-1">
            <p className="text-xs text-muted-foreground">Ort. Sağlık</p>
            <p className={cn("text-2xl font-bold tabular-nums", healthColor(dashboard.avg_health_score))}>
              {dashboard.avg_health_score !== null ? `${dashboard.avg_health_score.toFixed(1)}/10` : "—"}
            </p>
          </Card>
          <Card className="p-4 space-y-1">
            <p className="text-xs text-muted-foreground">Kritik Müşteri</p>
            <p className={cn("text-2xl font-bold tabular-nums", critical > 0 ? "text-red-400" : "text-foreground")}>
              {critical}
            </p>
          </Card>
        </div>
      )}

      {/* Profile info */}
      {profile && (
        <Card className="p-4">
          <div className="flex items-center flex-wrap gap-4 text-sm text-muted-foreground">
            <span className="flex items-center gap-1.5 font-medium text-foreground">
              <FileText className="h-4 w-4" />
              {profile.unvan ?? "SMMM"}
              {profile.oda_no && ` · Oda No: ${profile.oda_no}`}
            </span>
            {profile.il && (
              <span className="flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" />
                {profile.il}
              </span>
            )}
            {profile.telefon && (
              <span className="flex items-center gap-1">
                <Phone className="h-3.5 w-3.5" />
                {profile.telefon}
              </span>
            )}
          </div>
        </Card>
      )}

      {/* Clients table */}
      <Card className="overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold text-sm">Müşteri Listesi</h2>
          <span className="text-xs text-muted-foreground">{clients.length} müşteri</span>
        </div>

        {loading && clients.length === 0 ? (
          <div className="p-8 text-center space-y-3">
            {[1,2,3].map((i) => (
              <div key={i} className="flex items-center gap-3 animate-pulse">
                <div className="h-8 w-8 rounded bg-muted" />
                <div className="space-y-1 flex-1">
                  <div className="h-3 rounded bg-muted w-48" />
                  <div className="h-2 rounded bg-muted w-32" />
                </div>
              </div>
            ))}
          </div>
        ) : clients.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <Building2 className="h-10 w-10 text-muted-foreground mx-auto" />
            <p className="font-medium">Henüz müşteri yok</p>
            <p className="text-sm text-muted-foreground">
              Müşteri ekleyerek analiz başlatabilirsiniz.
            </p>
            <Button variant="outline" onClick={() => setShowAddClient(true)}>
              <Plus className="h-4 w-4 mr-1.5" />
              İlk Müşteriyi Ekle
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-muted-foreground">Firma</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-muted-foreground">Sektör</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-muted-foreground">İl</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-muted-foreground">Sağlık</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-muted-foreground">Durum</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-muted-foreground">Son Analiz</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-muted-foreground">İşlem</th>
                </tr>
              </thead>
              <tbody>
                {clients.map((client) => (
                  <ClientRow
                    key={client.id}
                    client={client}
                    onDelete={handleDelete}
                    onAnalyze={handleAnalyze}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Modals */}
      {showAddClient && (
        <AddClientModal
          onClose={() => setShowAddClient(false)}
          onSuccess={() => { setShowAddClient(false); fetchData(); }}
        />
      )}
    </main>
  );
}

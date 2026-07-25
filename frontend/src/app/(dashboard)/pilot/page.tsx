"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import {
  Users, Star, TrendingUp, MessageSquare, Copy, Check,
  Trash2, RefreshCw, Loader2, AlertCircle, Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Invite = {
  id: string;
  code: string;
  email: string | null;
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
  pilot_active: boolean;
  max_users: number;
  current_users: number;
  slots_remaining: number;
  accepting_new_users: boolean;
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
  if (score === null) return <p className="text-sm text-muted-foreground">Henüz veri yok</p>;
  const color = score >= 50 ? "text-emerald-400" : score >= 0 ? "text-yellow-400" : "text-destructive";
  return (
    <div className="flex items-end gap-2">
      <span className={cn("text-3xl font-bold tabular-nums", color)}>{score}</span>
      <span className="mb-1 text-xs text-muted-foreground">/ 100 NPS</span>
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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PilotAdminPage() {
  const { data: session } = useSession();
  const accessToken = (session as any)?.accessToken as string | undefined;

  const [invites, setInvites] = useState<Invite[]>([]);
  const [feedback, setFeedback] = useState<FeedbackEntry[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [status, setStatus] = useState<PilotStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  // Generate invite form
  const [genNote, setGenNote] = useState("");
  const [genEmail, setGenEmail] = useState("");
  const [generating, setGenerating] = useState(false);

  const h = () => ({
    "Content-Type": "application/json",
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  });

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [invRes, fbRes, sumRes, stRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/pilot/invites`, { headers: h() }),
        fetch(`${API_BASE}/api/v1/pilot/feedback?limit=50`, { headers: h() }),
        fetch(`${API_BASE}/api/v1/pilot/feedback/summary`, { headers: h() }),
        fetch(`${API_BASE}/api/v1/pilot/status`),
      ]);
      const [invData, fbData, sumData, stData] = await Promise.all([
        invRes.json(), fbRes.json(), sumRes.json(), stRes.json(),
      ]);
      setInvites(invData.data ?? []);
      setFeedback(fbData.data?.entries ?? []);
      setSummary(sumData.data ?? null);
      setStatus(stData.data ?? null);
    } catch {
      setError("Veriler yüklenemedi.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { if (accessToken) loadAll(); }, [accessToken]);

  async function generateInvite() {
    setGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/pilot/invite/generate`, {
        method: "POST",
        headers: h(),
        body: JSON.stringify({ note: genNote || null, email: genEmail || null, count: 1 }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? "Hata");
      await loadAll();
      setGenNote("");
      setGenEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setGenerating(false);
    }
  }

  async function revokeInvite(id: string) {
    await fetch(`${API_BASE}/api/v1/pilot/invite/${id}`, { method: "DELETE", headers: h() });
    setInvites((prev) => prev.filter((i) => i.id !== id));
  }

  async function copyInviteLink(code: string) {
    const url = `${window.location.origin}/auth/register?invite=${code}`;
    await navigator.clipboard.writeText(url).catch(() => {});
    setCopied(code);
    setTimeout(() => setCopied(null), 2000);
  }

  const unusedInvites = invites.filter((i) => !i.used);
  const usedInvites   = invites.filter((i) => i.used);

  return (
    <div className="space-y-6 p-5 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Pilot Program</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Davet kodları ve kullanıcı feedback'leri
          </p>
        </div>
        <button
          onClick={loadAll}
          disabled={loading}
          className="flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Yenile
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
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Toplam Kullanıcı" value={status.current_users} sub={`/ ${status.max_users} maks`} />
          <StatCard label="Boş Slot" value={status.slots_remaining} color={status.slots_remaining > 0 ? "text-emerald-400" : "text-destructive"} />
          <StatCard label="Bekleyen Davet" value={unusedInvites.length} />
          <StatCard label="Kullanılan Davet" value={usedInvites.length} />
        </div>
      )}

      {/* NPS + ratings */}
      {summary && summary.total_responses > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-4 text-sm font-medium">Feedback Özeti ({summary.total_responses} yanıt)</h2>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-xs text-muted-foreground">NPS Skoru</p>
              <NpsGauge score={summary.nps_score} />
              <div className="mt-2 flex gap-3 text-xs">
                <span className="text-emerald-400">😊 {summary.promoters} promoter</span>
                <span className="text-yellow-400">😐 {summary.passives} pasif</span>
                <span className="text-destructive">😞 {summary.detractors} detractor</span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Analiz kalitesi</span>
                <StarDisplay value={summary.avg_analysis_rating} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Doğruluk</span>
                <StarDisplay value={summary.avg_accuracy_rating} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Kullanışlılık</span>
                <StarDisplay value={summary.avg_usefulness_rating} />
              </div>
            </div>
          </div>

          {summary.top_benefits.length > 0 && (
            <div className="mt-4">
              <p className="mb-1.5 text-xs font-medium text-emerald-400">En çok beğenilen:</p>
              <ul className="space-y-1">
                {summary.top_benefits.slice(0, 5).map((b, i) => (
                  <li key={i} className="text-xs text-muted-foreground">• {b}</li>
                ))}
              </ul>
            </div>
          )}

          {summary.top_gaps.length > 0 && (
            <div className="mt-3">
              <p className="mb-1.5 text-xs font-medium text-orange-400">En çok eksik görülen:</p>
              <ul className="space-y-1">
                {summary.top_gaps.slice(0, 5).map((g, i) => (
                  <li key={i} className="text-xs text-muted-foreground">• {g}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Generate invite */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Plus className="h-4 w-4 text-muted-foreground" />
          Davet Kodu Oluştur
        </h2>
        <div className="flex flex-wrap gap-2">
          <input
            type="email"
            value={genEmail}
            onChange={(e) => setGenEmail(e.target.value)}
            placeholder="E-posta (isteğe bağlı)"
            className="h-8 flex-1 min-w-[160px] rounded-md border border-border bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <input
            type="text"
            value={genNote}
            onChange={(e) => setGenNote(e.target.value)}
            placeholder="Not (ör. şirket adı)"
            className="h-8 flex-1 min-w-[140px] rounded-md border border-border bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <button
            onClick={generateInvite}
            disabled={generating}
            className="flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
            Oluştur
          </button>
        </div>
      </div>

      {/* Invite list */}
      {invites.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">Davet Kodları ({invites.length})</h2>
          </div>
          <div className="divide-y divide-border/50">
            {invites.map((inv) => (
              <div key={inv.id} className={cn("flex items-center gap-3 px-4 py-3", inv.used && "opacity-50")}>
                <code className="flex-1 min-w-0 truncate rounded bg-muted px-2 py-0.5 font-mono text-xs">
                  {inv.code}
                </code>
                {inv.note && <span className="text-xs text-muted-foreground">{inv.note}</span>}
                {inv.used ? (
                  <span className="text-xs text-emerald-400">Kullanıldı</span>
                ) : (
                  <>
                    <button
                      onClick={() => copyInviteLink(inv.code)}
                      className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
                      aria-label="Linki kopyala"
                    >
                      {copied === inv.code ? (
                        <Check className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      onClick={() => revokeInvite(inv.id)}
                      className="rounded p-1 text-muted-foreground transition-colors hover:text-destructive"
                      aria-label="İptal et"
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
            <h2 className="text-sm font-medium">Son Feedback'ler ({feedback.length})</h2>
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
                      NPS {f.nps_score}
                    </span>
                  )}
                  {f.analysis_rating && <StarDisplay value={f.analysis_rating} />}
                  <span className="text-xs text-muted-foreground">
                    {new Date(f.created_at).toLocaleDateString("tr-TR")}
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

      {!loading && invites.length === 0 && feedback.length === 0 && (
        <div className="rounded-lg border border-border bg-card px-4 py-12 text-center">
          <Users className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium">Pilot program başlamadı</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Yukarıdan bir davet kodu oluşturun ve paylaşın.
          </p>
        </div>
      )}
    </div>
  );
}

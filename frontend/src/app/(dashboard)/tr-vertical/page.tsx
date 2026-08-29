"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Play, CheckCircle2, AlertTriangle, ShieldAlert, FileText, Loader2,
  ArrowRight, TrendingUp, TrendingDown, Landmark, Download,
} from "lucide-react";
import { cn, formatCurrency } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfidenceBreakdown } from "@/components/ui/confidence-breakdown";
import { DefensibilityPacketCard } from "@/components/smmm/DefensibilityPacketCard";
import { listJobs, type JobSummary } from "@/lib/api/cfo";
import {
  runTrVertical, downloadTrBoardDeck, type TrVerticalResult,
} from "@/lib/api/muhasebe";

const STAGES: Array<TrVerticalResult["stage"]> = [
  "cfo", "accounting", "board_deck", "done",
];
const STAGE_LABEL: Record<string, string> = {
  ingest: "Veri Alımı",
  cfo: "CFO Analizi",
  accounting: "TR Muhasebe (THP)",
  board_deck: "Yönetim Kurulu Sunumu",
  done: "Tamamlandı",
};

function StageTrack({ current }: { current: TrVerticalResult["stage"] }) {
  const idx = STAGES.indexOf(current);
  return (
    <div className="flex items-center gap-2 text-xs">
      {STAGES.map((s, i) => (
        <div key={s} className="flex items-center gap-2">
          <span
            className={cn(
              "rounded-full px-2.5 py-1 border",
              i < idx && "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
              i === idx && "border-primary/50 bg-primary/10 text-foreground",
              i > idx && "border-border text-muted-foreground",
            )}
          >
            {STAGE_LABEL[s]}
          </span>
          {i < STAGES.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
        </div>
      ))}
    </div>
  );
}

function ApprovalGate({ result }: { result: TrVerticalResult }) {
  if (!result.approval_required) {
    return (
      <Card className="border-emerald-500/30 bg-emerald-500/5 p-4">
        <div className="flex items-center gap-2 text-emerald-400 font-medium">
          <CheckCircle2 className="h-5 w-5" />
          Onay gerekmiyor — otomatik ilerleyebilir
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          CFO analizi, mutabakat ve yevmiye kayıtları tutarlı. Yine de nihai kararı
          insan onaylar.
        </p>
      </Card>
    );
  }
  return (
    <Card className="border-amber-500/40 bg-amber-500/5 p-4">
      <div className="flex items-center gap-2 text-amber-400 font-medium">
        <ShieldAlert className="h-5 w-5" />
        İnsan onayı bekleniyor
      </div>
      <ul className="mt-2 space-y-1 text-sm">
        {result.approval_reasons.map((r, i) => (
          <li key={i} className="flex gap-2">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
            <span>{r}</span>
          </li>
        ))}
      </ul>
      <Link
        href="/smmm-onay"
        className="mt-3 inline-flex items-center gap-1 text-sm text-primary hover:underline"
      >
        SMMM onay kuyruğuna git <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </Card>
  );
}

function PnlSnapshot({ result }: { result: TrVerticalResult }) {
  const pnl = result.cfo.pnl;
  if (!pnl) return null;
  const net = (pnl.net_income ?? 0) / 100;
  const positive = net >= 0;
  const items = [
    { label: "Gelir", value: (pnl.revenue ?? 0) / 100 },
    { label: "Brüt Kâr", value: (pnl.gross_profit ?? 0) / 100 },
    { label: "FAVÖK", value: (pnl.ebitda ?? 0) / 100 },
    { label: "Net Kâr / Zarar", value: net, accent: true },
  ];
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        {positive ? (
          <TrendingUp className="h-4 w-4 text-emerald-400" />
        ) : (
          <TrendingDown className="h-4 w-4 text-red-400" />
        )}
        CFO Özeti
        <span className="text-muted-foreground">
          · {result.cfo.transaction_count ?? 0} işlem
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {items.map((it) => (
          <div key={it.label}>
            <div className="text-xs text-muted-foreground">{it.label}</div>
            <div
              className={cn(
                "text-lg font-semibold",
                it.accent && (positive ? "text-emerald-400" : "text-red-400"),
              )}
            >
              {formatCurrency(it.value)}
            </div>
          </div>
        ))}
      </div>
      {typeof pnl.net_margin === "number" && (
        <div className="mt-2 text-xs text-muted-foreground">
          Net marj: %{(pnl.net_margin * 100).toFixed(1)} · min. güven:{" "}
          {((result.cfo.min_confidence ?? 0) * 100).toFixed(0)}%
        </div>
      )}
    </Card>
  );
}

function BoardDeckCard({ jobId, donem, sizeKb }: { jobId: string; donem: string; sizeKb: number }) {
  const [downloading, setDownloading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const download = useCallback(async () => {
    setDownloading(true);
    setErr(null);
    try {
      const blob = await downloadTrBoardDeck(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `yonetim-kurulu-${donem || jobId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setErr("PDF indirilemedi.");
    } finally {
      setDownloading(false);
    }
  }, [jobId, donem]);

  return (
    <Card className="flex flex-wrap items-center gap-3 p-4 text-sm">
      <FileText className="h-4 w-4 text-primary" />
      Yönetim kurulu sunumu oluşturuldu
      <span className="text-muted-foreground">({sizeKb.toFixed(1)} KB)</span>
      <Button
        onClick={download}
        disabled={downloading}
        variant="outline"
        className="ml-auto gap-2"
      >
        {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        İndir
      </Button>
      {err && <span className="w-full text-red-400">{err}</span>}
    </Card>
  );
}

function AccountingSummary({ result }: { result: TrVerticalResult }) {
  const acc = result.accounting;
  if (!acc) return null;
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Landmark className="h-4 w-4 text-primary" /> TR Muhasebe (THP)
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-sm">
        <div>
          <div className="text-xs text-muted-foreground">İşlem</div>
          <div className="font-semibold">{acc.islem_sayisi}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Yevmiye Kaydı</div>
          <div className="font-semibold">{acc.kayit_sayisi}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Onay Bekleyen</div>
          <div className={cn("font-semibold", acc.onay_bekleyen > 0 && "text-amber-400")}>
            {acc.onay_bekleyen}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Denge</div>
          <div className={cn("font-semibold", acc.dengeli ? "text-emerald-400" : "text-red-400")}>
            {acc.dengeli ? "Dengeli" : "Dengesiz"}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function TrVerticalPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobId, setJobId] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TrVerticalResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listJobs()
      .then((j) => {
        const done = j.filter((x) => x.status === "completed");
        setJobs(done);
        if (done[0]) setJobId(done[0].job_id);
      })
      .catch((e) => setError(e.message));
  }, []);

  const run = useCallback(async () => {
    if (!jobId) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const resp = await runTrVertical(jobId, { companyName: companyName || undefined });
      setResult(resp.data);
      if (resp.error) setError(resp.error);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bilinmeyen hata");
    } finally {
      setRunning(false);
    }
  }, [jobId, companyName]);

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">TR Muhasebe Otopilotu (L3)</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Yüklenen dosyayı tek geçişte CFO analizi → THP yevmiye kayıtları → yönetim
          kurulu sunumu boyunca işler ve tek bir onay kapısında durur. Otomatik onay yok.
        </p>
      </div>

      <Card className="space-y-3 p-4">
        <label className="block text-sm font-medium">Tamamlanmış analiz işi</label>
        <select
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        >
          {jobs.length === 0 && <option value="">Tamamlanmış iş yok</option>}
          {jobs.map((j) => (
            <option key={j.job_id} value={j.job_id}>
              {j.filename} · {new Date(j.created_at).toLocaleDateString("tr-TR")}
            </option>
          ))}
        </select>
        <input
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          placeholder="Şirket adı (opsiyonel)"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <Button onClick={run} disabled={!jobId || running} className="gap-2">
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {running ? "Çalışıyor…" : "Otopilotu Başlat"}
        </Button>
      </Card>

      {error && (
        <Card className="border-red-500/40 bg-red-500/5 p-3 text-sm text-red-400">
          {error}
        </Card>
      )}

      {result && (
        <div className="space-y-4">
          <StageTrack current={result.stage} />
          <ApprovalGate result={result} />
          <PnlSnapshot result={result} />
          <ConfidenceBreakdown data={result.cfo.confidence_breakdown} />
          <AccountingSummary result={result} />
          {result.stage === "done" && jobId && (
            <DefensibilityPacketCard jobId={jobId} />
          )}

          {result.reconciliation && result.reconciliation.action !== "proceed" && (
            <Card className="border-amber-500/40 bg-amber-500/5 p-4 text-sm">
              <div className="font-medium text-amber-400">Mutabakat: {result.reconciliation.action}</div>
              {result.reconciliation.identity_failures.map((f, i) => (
                <div key={i}>• {f}</div>
              ))}
              {result.reconciliation.ungrounded_claims.map((f, i) => (
                <div key={`u${i}`}>• dayanaksız: {f}</div>
              ))}
            </Card>
          )}

          {result.board_deck_pdf_size > 0 && (
            <BoardDeckCard
              jobId={jobId}
              donem={companyName}
              sizeKb={result.board_deck_pdf_size / 1024}
            />
          )}

          {result.errors.length > 0 && (
            <Card className="border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">
              {result.errors.map((e, i) => (
                <div key={i}>{e}</div>
              ))}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

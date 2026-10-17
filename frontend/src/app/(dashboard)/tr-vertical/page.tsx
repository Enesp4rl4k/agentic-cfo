"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Play, CheckCircle2, AlertTriangle, ShieldAlert, FileText, Loader2,
  ArrowRight, TrendingUp, TrendingDown, Landmark, Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfidenceBreakdown } from "@/components/ui/confidence-breakdown";
import { DefensibilityPacketCard } from "@/components/smmm/DefensibilityPacketCard";
import { EDefterCard } from "@/components/smmm/EDefterCard";
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import type { MessageTree } from "@/lib/i18n";
import { listJobs, type JobSummary } from "@/lib/api/cfo";
import {
  runTrVertical, downloadTrBoardDeck, hasApprovedJournal,
  type TrVerticalResult,
} from "@/lib/api/muhasebe";

const STAGES: Array<TrVerticalResult["stage"]> = [
  "cfo", "accounting", "board_deck", "done",
];

// Backend stage keys → message-tree keys.
const STAGE_KEY: Record<string, keyof MessageTree["trVertical"]["stages"]> = {
  ingest: "ingest",
  cfo: "cfo",
  accounting: "accounting",
  board_deck: "boardDeck",
  done: "done",
};

function StageTrack({ current }: { current: TrVerticalResult["stage"] }) {
  const idx = STAGES.indexOf(current);
  const { t } = useI18n();
  const stages = t.trVertical.stages;
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
            {stages[STAGE_KEY[s]]}
          </span>
          {i < STAGES.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
        </div>
      ))}
    </div>
  );
}

function ApprovalGate({ result }: { result: TrVerticalResult }) {
  const { t } = useI18n();
  const approval = t.trVertical.approval;
  if (!result.approval_required) {
    return (
      <Card className="border-emerald-500/30 bg-emerald-500/5 p-4">
        <div className="flex items-center gap-2 text-emerald-400 font-medium">
          <CheckCircle2 className="h-5 w-5" />
          {approval.autoOk}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{approval.autoOkBody}</p>
      </Card>
    );
  }
  return (
    <Card className="border-amber-500/40 bg-amber-500/5 p-4">
      <div className="flex items-center gap-2 text-amber-400 font-medium">
        <ShieldAlert className="h-5 w-5" />
        {approval.waiting}
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
        {approval.queueLink} <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </Card>
  );
}

function PnlSnapshot({ result }: { result: TrVerticalResult }) {
  const { t } = useI18n();
  const fmt = useCurrencyFormat();
  const pnlSnapshot = t.trVertical.pnl;
  const pnl = result.cfo.pnl;
  if (!pnl) return null;
  const net = (pnl.net_income ?? 0) / 100;
  const positive = net >= 0;
  const items = [
    { label: pnlSnapshot.revenue, value: (pnl.revenue ?? 0) / 100 },
    { label: pnlSnapshot.grossProfit, value: (pnl.gross_profit ?? 0) / 100 },
    { label: pnlSnapshot.ebitda, value: (pnl.ebitda ?? 0) / 100 },
    { label: pnlSnapshot.netProfit, value: net, accent: true },
  ];
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        {positive ? (
          <TrendingUp className="h-4 w-4 text-emerald-400" />
        ) : (
          <TrendingDown className="h-4 w-4 text-red-400" />
        )}
        {pnlSnapshot.summary}
        <span className="text-muted-foreground">
          · {pnlSnapshot.transactions.replace("{count}", String(result.cfo.transaction_count ?? 0))}
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
              {fmt(it.value)}
            </div>
          </div>
        ))}
      </div>
      {typeof pnl.net_margin === "number" && (
        <div className="mt-2 text-xs text-muted-foreground">
          {pnlSnapshot.marginLine
            .replace("{margin}", (pnl.net_margin * 100).toFixed(1))
            .replace("{confidence}", ((result.cfo.min_confidence ?? 0) * 100).toFixed(0))}
        </div>
      )}
    </Card>
  );
}

function BoardDeckCard({ jobId, donem, sizeKb }: { jobId: string; donem: string; sizeKb: number }) {
  const [downloading, setDownloading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { t } = useI18n();
  const deck = t.trVertical.deck;

  const download = useCallback(async () => {
    setDownloading(true);
    setErr(null);
    try {
      const blob = await downloadTrBoardDeck(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      // i18n-exempt: download file name, not user-facing UI copy
      a.download = `yonetim-kurulu-${donem || jobId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setErr(deck.downloadError);
    } finally {
      setDownloading(false);
    }
  }, [jobId, donem, deck]);

  return (
    <Card className="flex flex-wrap items-center gap-3 p-4 text-sm">
      <FileText className="h-4 w-4 text-primary" />
      {deck.ready}
      <span className="text-muted-foreground">
        {deck.size.replace("{size}", sizeKb.toFixed(1))}
      </span>
      <Button
        onClick={download}
        disabled={downloading}
        variant="outline"
        className="ml-auto gap-2"
      >
        {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        {deck.download}
      </Button>
      {err && <span className="w-full text-red-400">{err}</span>}
    </Card>
  );
}

function AccountingSummary({ result }: { result: TrVerticalResult }) {
  const { t } = useI18n();
  const acc = result.accounting;
  const summary = t.trVertical.accounting;
  if (!acc) return null;
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Landmark className="h-4 w-4 text-primary" /> {summary.title}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-sm">
        <div>
          <div className="text-xs text-muted-foreground">{summary.transactions}</div>
          <div className="font-semibold">{acc.islem_sayisi}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{summary.journalEntries}</div>
          <div className="font-semibold">{acc.kayit_sayisi}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{summary.pendingApproval}</div>
          <div className={cn("font-semibold", acc.onay_bekleyen > 0 && "text-amber-400")}>
            {acc.onay_bekleyen}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{summary.balance}</div>
          <div className={cn("font-semibold", acc.dengeli ? "text-emerald-400" : "text-red-400")}>
            {acc.dengeli ? summary.balanced : summary.unbalanced}
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
  // The run result lives only in page state, so the tail of the chain —
  // the sealed packet and the e-Defter built from it — used to vanish the
  // moment the user walked to the approval queue and came back. Ask the
  // server instead of relying on what this page happens to remember.
  const [journalReady, setJournalReady] = useState(false);

  const { t, locale } = useI18n();
  const tv = t.trVertical;
  const dateTag = locale === "tr" ? "tr-TR" : "en-US";

  useEffect(() => {
    listJobs()
      .then((j) => {
        const done = j.filter((x) => x.status === "completed");
        setJobs(done);
        if (done[0]) setJobId(done[0].job_id);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!jobId) { setJournalReady(false); return; }
    let live = true;
    void hasApprovedJournal(jobId).then((ok) => { if (live) setJournalReady(ok); });
    return () => { live = false; };
  }, [jobId]);

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
      setError(e instanceof Error ? e.message : tv.unknownError);
    } finally {
      setRunning(false);
    }
  }, [jobId, companyName, tv]);

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{tv.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{tv.subtitle}</p>
      </div>

      <Card className="space-y-3 p-4">
        <label className="block text-sm font-medium">{tv.jobLabel}</label>
        <select
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        >
          {jobs.length === 0 && <option value="">{tv.noJobs}</option>}
          {jobs.map((j) => (
            <option key={j.job_id} value={j.job_id}>
              {j.filename} · {new Date(j.created_at).toLocaleDateString(dateTag)}
            </option>
          ))}
        </select>
        <input
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          placeholder={tv.companyPlaceholder}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <Button onClick={run} disabled={!jobId || running} className="gap-2">
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {running ? tv.running : tv.start}
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


          {result.reconciliation && result.reconciliation.action !== "proceed" && (
            <Card className="border-amber-500/40 bg-amber-500/5 p-4 text-sm">
              <div className="font-medium text-amber-400">
                {tv.reconciliation.replace("{action}", result.reconciliation.action)}
              </div>
              {result.reconciliation.identity_failures.map((f, i) => (
                <div key={i}>• {f}</div>
              ))}
              {result.reconciliation.ungrounded_claims.map((f, i) => (
                <div key={`u${i}`}>• {tv.ungrounded}: {f}</div>
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

      {/* The tail of the chain, shown whenever the job actually has an approved
          journal — not only while this page still remembers running it. The
          natural path is run → approve the queue → come back and seal, and that
          walk used to leave both cards behind. */}
      {jobId && (journalReady || result?.stage === "done") && (
        <div className="space-y-4">
          <DefensibilityPacketCard jobId={jobId} />
          {/* Built from the rows the packet seals, so it belongs next to it. */}
          <EDefterCard jobId={jobId} />
        </div>
      )}
    </div>
  );
}

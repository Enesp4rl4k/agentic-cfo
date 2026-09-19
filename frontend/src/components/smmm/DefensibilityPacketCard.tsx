"use client";

import { useCallback, useState } from "react";
import { ShieldCheck, Download, Loader2, Lock, FileSignature, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  buildDefensibilityPacket,
  finalizeDefensibilityPacket,
  exportDefensibilityPacket,
  type DefensibilityPacket,
} from "@/lib/api/smmm";

const DS_LABEL: Record<string, string> = {
  ai_auto_posted: "AI otomatik",
  human_approved: "SMMM onayladı",
  human_corrected: "SMMM düzeltti",
  rejected: "Reddedildi",
  pending_review: "Onay bekliyor",
};

/**
 * SMMM Defensibility Packet (#4) — one hash-sealed record the accountant can
 * hand a tax inspector: every entry's basis, AI confidence, and who reviewed it.
 */
export function DefensibilityPacketCard({ jobId, period }: { jobId: string; period?: string }) {
  const [packet, setPacket] = useState<DefensibilityPacket | null>(null);
  const [statement, setStatement] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const build = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      setPacket(await buildDefensibilityPacket(jobId, period));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "paket oluşturulamadı");
    } finally {
      setBusy(false);
    }
  }, [jobId, period]);

  const finalize = useCallback(async () => {
    if (!packet || !statement.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      setPacket(await finalizeDefensibilityPacket(packet.id, statement.trim()));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "kesinleştirilemedi");
    } finally {
      setBusy(false);
    }
  }, [packet, statement]);

  const download = useCallback(async () => {
    if (!packet) return;
    const blob = await exportDefensibilityPacket(packet.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `savunulabilirlik-${packet.job_id}.${blob.type === "application/pdf" ? "pdf" : "txt"}`;
    a.click();
    URL.revokeObjectURL(url);
  }, [packet]);

  const s = packet?.summary;

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Mali Müşavir Savunulabilirlik Paketi
        {packet?.status === "finalized" && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <Lock className="h-3.5 w-3.5" /> kesinleştirildi
          </span>
        )}
      </div>

      {!packet && (
        <Button onClick={build} disabled={busy} className="gap-2">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
          Paketi oluştur
        </Button>
      )}

      {s && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-sm">
            <Stat label="Kayıt" value={s.entry_count} />
            <Stat label="İnsan incelemesi" value={s.human_reviewed} />
            <Stat label="AI otomatik" value={s.ai_auto_posted} />
            <Stat
              label="Onay bekleyen"
              value={s.pending_review}
              tone={s.pending_review > 0 ? "text-amber-400" : undefined}
            />
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(s.by_decision_source).map(([k, v]) => (
              <span key={k} className="rounded border border-border px-2 py-0.5">
                {DS_LABEL[k] ?? k}: {v}
              </span>
            ))}
          </div>
          <p
            className={cn(
              "text-xs",
              s.defensible ? "text-emerald-400" : "text-amber-400"
            )}
          >
            {s.defensible
              ? "Tüm kayıtlar ya insan tarafından incelendi ya da yüksek güvenle otomatik atıldı."
              : "Bazı kayıtlar hâlâ onay bekliyor — kesinleştirmeden önce SMMM kuyruğunu bitirin."}
          </p>
          {packet.content_hash && (
            <p className="break-all font-mono text-[10px] text-muted-foreground">
              SHA-256: {packet.content_hash}
            </p>
          )}

          {packet.status === "draft" ? (
            <div className="space-y-2">
              <textarea
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
                placeholder="Mali müşavir beyanı — 'Bu dönem kayıtlarını inceledim ve uygun buldum. SM. …'"
                rows={2}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
              <div className="flex gap-2">
                <Button onClick={finalize} disabled={busy || !statement.trim()} className="gap-2">
                  <FileSignature className="h-4 w-4" /> Kesinleştir ve mühürle
                </Button>
                <Button onClick={build} disabled={busy} variant="outline">
                  Yenile
                </Button>
              </div>
            </div>
          ) : (
            <Button onClick={download} variant="outline" className="gap-2">
              <Download className="h-4 w-4" /> Denetim belgesini indir
            </Button>
          )}
        </>
      )}

      {err && (
        <p className="flex items-center gap-1 text-xs text-red-400">
          <AlertTriangle className="h-3.5 w-3.5" /> {err}
        </p>
      )}
    </Card>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("font-semibold", tone)}>{value}</div>
    </div>
  );
}

"use client";

import { useCallback, useState } from "react";
import { AlertTriangle, BookOpen, Download, Loader2, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  downloadEDefter,
  type EDefterFile,
  type EDefterKind,
} from "@/lib/api/muhasebe";

const LABEL: Record<EDefterKind, string> = {
  yevmiye: "Yevmiye defteri",
  kebir: "Defter-i kebir",
};

/**
 * GİB e-Defter (XBRL GL) — built from the rows the defensibility packet sealed.
 *
 * The backend validates this against the edefter.xsd GİB publishes, so the file
 * is structurally a real e-Defter. It is still **not filable**: that needs a
 * XAdES signature from a mali mühür and a berat, neither of which exists here.
 *
 * Those two facts have to stay apart on screen. A download button next to a
 * sealed packet reads as "this is done"; the whole point of the packet is that
 * the record says what actually happened, and the same has to be true of the
 * ledger built from it.
 */
export function EDefterCard({ jobId }: { jobId: string }) {
  const [busy, setBusy] = useState<EDefterKind | null>(null);
  const [last, setLast] = useState<EDefterFile | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const grab = useCallback(
    async (kind: EDefterKind) => {
      setBusy(kind);
      setErr(null);
      try {
        const file = await downloadEDefter(jobId, kind);
        const url = URL.createObjectURL(file.blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = file.fileName;
        a.click();
        URL.revokeObjectURL(url);
        setLast(file);
      } catch (e) {
        // A 409 here means the journal does not balance, which is worth
        // reading rather than swallowing into "bir hata oluştu".
        const detail =
          e && typeof e === "object" && "response" in e
            ? ((e as { response?: { data?: { error?: string; detail?: string } } })
                .response?.data?.error ??
              (e as { response?: { data?: { detail?: string } } }).response?.data
                ?.detail)
            : undefined;
        setErr(detail ?? (e instanceof Error ? e.message : "defter indirilemedi"));
      } finally {
        setBusy(null);
      }
    },
    [jobId],
  );

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <BookOpen className="h-4 w-4 text-primary" />
        GİB e-Defter (XBRL GL)
      </div>

      <p className="text-xs text-muted-foreground">
        Mühürlenen yevmiye kayıtlarından üretilir — beyan edilen defter ile
        denetlenen kayıt aynı satırlardır. GİB&apos;in yayımladığı{" "}
        <code className="font-mono">edefter.xsd</code> şemasına göre doğrulanır.
      </p>

      <div className="flex flex-wrap gap-2">
        {(Object.keys(LABEL) as EDefterKind[]).map((kind) => (
          <Button
            key={kind}
            onClick={() => grab(kind)}
            disabled={busy !== null}
            variant="outline"
            className="gap-2"
          >
            {busy === kind ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {LABEL[kind]}
          </Button>
        ))}
      </div>

      {/* Never hidden behind a tooltip or shown only after a download: someone
          who takes this file to their accountant has to know what it is not. */}
      <div className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/10 p-2.5">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
        <p className="text-xs text-amber-200/90">
          <strong>Bu defter GİB&apos;e yüklenemez.</strong> Beyan için mali mühür
          ya da nitelikli e-imza ile XAdES imzalanması ve beratının alınması
          gerekir; ikisi de bu sistemde yok. Dosya yapısal olarak tamdır, hukuken
          eksiktir — mali müşavirinizle birlikte kullanın.
        </p>
      </div>

      {last && (
        <div className="space-y-1 text-xs text-muted-foreground">
          <div>
            <span className="font-mono">{last.fileName}</span> — {last.entryCount}{" "}
            kayıt, {last.lineCount} satır
          </div>
          <div className="break-all font-mono text-[10px]">
            SHA-256: {last.sha256}
          </div>
        </div>
      )}

      {err && (
        <p className="flex items-start gap-1 text-xs text-red-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {err}
        </p>
      )}
    </Card>
  );
}

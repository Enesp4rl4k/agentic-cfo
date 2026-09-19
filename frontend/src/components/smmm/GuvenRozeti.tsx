"use client";

import { ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import { cn } from "@/lib/utils";

/** Mirrors `app/services/accounting/guven.py` `Guven.to_dict()`. */
export interface Guven {
  seviye: "guclu_kural" | "kural" | "zayif_kural" | "llm" | "varsayilan";
  etiket: string;
  aciklama: string;
  kontrol: string;
  kanit: string;
  dogru: number;
  toplam: number;
  kaynak: "korpus" | "kurum" | "olculmedi";
  olcum: string;
  skor: number;
}

/** Automatic approval needs this lower bound; matches the authority matrix. */
const OTOMATIK_ESIK = 0.8;

const TONE: Record<Guven["seviye"], string> = {
  guclu_kural: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  kural: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  zayif_kural: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  llm: "border-orange-500/30 bg-orange-500/10 text-orange-300",
  varsayilan: "border-red-500/30 bg-red-500/10 text-red-300",
};

/**
 * Why this entry can or cannot be trusted.
 *
 * The queue used to print "%30 güven": keyword arithmetic presented as a
 * probability. This shows what the classification rests on (the evidence
 * level and what matched), how often that kind of evidence has been right —
 * on the test set, or on this organisation's own approvals once there are
 * enough — and what the reviewer should check. The colour follows the kind of
 * evidence, not the number, so a thin measurement cannot look reassuring.
 */
export function GuvenRozeti({ guven, compact = false }: { guven: Guven | null | undefined; compact?: boolean }) {
  if (!guven) {
    return (
      <span className="text-[11px] text-muted-foreground" title="Bu kayıt güven ölçümü eklenmeden önce oluşturuldu.">
        eski kayıt — güven ölçülmedi
      </span>
    );
  }
  const yeterli = guven.skor >= OTOMATIK_ESIK;
  const Icon = guven.toplam === 0 ? ShieldQuestion : yeterli ? ShieldCheck : ShieldAlert;
  const pct = Math.round(guven.skor * 100);

  return (
    <div className="space-y-1">
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
          TONE[guven.seviye] ?? "border-border text-muted-foreground",
        )}
        title={guven.aciklama}
      >
        <Icon className="h-3 w-3" aria-hidden="true" />
        {guven.etiket}
        {guven.toplam > 0 && (
          <span className="tabular-nums opacity-80" title="Ölçülen isabetin %95 güvenle en düşük değeri">
            · en az %{pct}
          </span>
        )}
      </span>
      {!compact && (
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          <span className="font-mono text-foreground/80">{guven.kanit}</span>
          {" · "}
          {guven.olcum}
          {" · "}
          {yeterli
            ? "otomatik onay için yeterli"
            : `otomatik onay için %${Math.round(OTOMATIK_ESIK * 100)} gerekir`}
          <span className="block text-muted-foreground/80">{guven.kontrol}</span>
        </p>
      )}
    </div>
  );
}

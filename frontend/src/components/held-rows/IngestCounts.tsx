"use client";

import { useI18n } from "@/hooks/useI18n";

/** What the backend says about an upload's rows (app/services/ingest/summary.py): where every row went. */
export interface IngestSummary {
  processed?: number;
  held?: number;
  rows_read?: number;
  summary_lines_skipped?: number;
  skipped_lines?: Array<{ description: string; date: string }>;
  account_lines_skipped?: number;
  unaccounted?: number;
  reader_fallback?: boolean;
  /** Text (PDF) statements: was the running balance chained? Never presented as reconciled when it was not. */
  balance_check?: "verified" | "verified_partial" | "unverified" | null;
  /** Rows with no balance in a statement whose other rows have one: held, not vouched for by the chain. */
  outside_chain?: number;
  /** PDF pages that yielded no text (app/services/page_gap.py): per page, Turkish and English, and whether rows may be missing. */
  pages_not_read?: Array<{
    file: string;
    pages: Array<{ page: number; state: "hold" | "scan_verified" | "note"; tr: string; en: string }>;
  }>;
}

function PagesNotRead({ ingest }: Readonly<{ ingest: IngestSummary }>) {
  const { t, locale } = useI18n();
  const files = (ingest.pages_not_read ?? []).filter((f) => f.pages.length > 0);
  if (files.length === 0) return null;
  const held = files.some((f) => f.pages.some((p) => p.state === "hold"));
  return (
    <div className="space-y-1 text-sm" data-testid="pages-not-read">
      <p className={held ? "font-medium text-amber-500" : "font-medium"} role={held ? "alert" : undefined}>
        {t.heldRows.ingestPagesTitle}
        {held && `: ${t.heldRows.ingestPagesHeld}`}
      </p>
      <ul className="list-inside list-disc text-xs text-muted-foreground">
        {files.flatMap((f) =>
          f.pages.map((p) => (
            <li key={`${f.file}-${p.page}`} className={p.state === "hold" ? "text-amber-500" : undefined}>
              {files.length > 1 ? `${f.file}: ` : ""}
              {locale === "en" ? p.en : p.tr}
            </li>
          )),
        )}
      </ul>
    </div>
  );
}

/**
 * "N satır okundu: A kaydedildi, B kararınızı bekliyor, C özet satırı atlandı", with the skipped lines
 * viewable. Nothing the reader was handed disappears unseen: a count that does not add up is said as such.
 * Renders nothing for an upload that reported no row counts (e.g. an invoice XML).
 */
export function IngestCounts({ ingest }: Readonly<{ ingest?: IngestSummary | null }>) {
  const { t } = useI18n();
  const copy = t.heldRows;
  if (!ingest) return null;
  if (!ingest.rows_read) return <PagesNotRead ingest={ingest} />;
  const skipped = ingest.summary_lines_skipped ?? 0;
  const transfers = ingest.account_lines_skipped ?? 0;
  const sentence = copy.ingestRead
    .replace("{read}", String(ingest.rows_read))
    .replace("{saved}", String(ingest.processed ?? 0))
    .replace("{held}", String(ingest.held ?? 0))
    .replace("{skipped}", String(skipped));
  const lines = ingest.skipped_lines ?? [];
  return (
    <div className="space-y-1 text-sm" data-testid="ingest-counts">
      <p className="font-medium">
        {sentence}
        {transfers > 0 && `, ${copy.ingestTransfers.replace("{count}", String(transfers))}`}
      </p>
      {lines.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{copy.ingestSkippedTitle}</summary>
          <ul className="mt-1 list-inside list-disc">
            {lines.map((l, i) => (
              <li key={`${l.description}-${i}`}>{l.date ? `${l.date} · ${l.description}` : l.description}</li>
            ))}
          </ul>
        </details>
      )}
      {(ingest.unaccounted ?? 0) > 0 && (
        <p role="alert" className="text-amber-500">
          {copy.ingestLost.replace("{count}", String(ingest.unaccounted))}
        </p>
      )}
      {ingest.balance_check === "verified" && !ingest.outside_chain && <p className="text-xs text-muted-foreground">{copy.ingestBalanceVerified}</p>}
      {ingest.balance_check === "verified_partial" && (
        <p className="text-xs text-amber-500">
          {copy.ingestBalancePartial
            .replace("{verified}", String(ingest.processed ?? 0))
            .replace("{held}", String(ingest.held ?? 0))}
        </p>
      )}
      {ingest.balance_check === "unverified" && <p className="text-xs text-amber-500">{copy.ingestBalanceUnverified}</p>}
      {(ingest.outside_chain ?? 0) > 0 && (
        <p className="text-xs text-amber-500">{copy.ingestOutsideChain.replace("{count}", String(ingest.outside_chain))}</p>
      )}
      {ingest.reader_fallback && <p className="text-xs text-muted-foreground">{copy.ingestFallback}</p>}
      <PagesNotRead ingest={ingest} />
    </div>
  );
}

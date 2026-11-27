"use client";

import { useState } from "react";
import { apiClient } from "@/lib/api/client";
import { useI18n } from "@/hooks/useI18n";
import { detailOf, type AiEgressView } from "./types";

type Mode = "off" | "masked" | "raw";
const MODES: Mode[] = ["off", "masked", "raw"];

function formatBytes(n: number, locale: string): string {
  if (n < 1024) return `${n.toLocaleString(locale)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} KB`;
  return `${(n / (1024 * 1024)).toLocaleString(locale, { maximumFractionDigits: 1 })} MB`;
}

/**
 * "Yapay zekâya giden veri": what may leave for a language model, to which provider, in which mode, and how much
 * did in the last 30 days (counts only: no payload is stored, so none can be shown). Owner-only: the backend
 * sends `ai_egress` to the owner alone. It describes; it never says a transfer is lawful.
 */
export function AiEgressCard({ view, onChanged }: { view: AiEgressView; onChanged: () => void }) {
  const { t, locale } = useI18n();
  const a = t.settingsPrivacy.aiEgress;
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function choose(mode: Mode | null) {
    setBusy(true);
    setNote(null);
    try {
      await apiClient.put("/privacy/ai-data-mode", { mode });
      setNote(a.saved);
      onChanged();
    } catch (e) {
      setNote(detailOf(e) ?? a.failed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4 rounded-lg border border-border p-4" aria-labelledby="privacy-ai">
      <h2 id="privacy-ai" className="text-lg font-semibold">{a.title}</h2>
      <p className="text-sm text-muted-foreground">{a.intro}</p>

      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">{a.provider}</dt>
          <dd className="font-medium">{view.provider_host ?? a.providerDefault} · {(view.models?.length ? view.models : [view.model]).join(", ")}</dd>
          <dd className={view.provider_is_local ? "text-emerald-700" : "text-amber-700"}>
            {view.provider_is_local ? a.local : a.outside}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{a.current}</dt>
          <dd className="font-medium">{a.modes[view.mode].label}</dd>
          <dd className="text-muted-foreground">
            {view.source === "organisation" ? a.sourceOrg : a.sourcePlatform.replace("{mode}", a.modes[view.platform_mode].label)}
          </dd>
        </div>
      </dl>

      <fieldset className="space-y-2" disabled={busy}>
        <legend className="text-sm font-medium">{a.chooseTitle}</legend>
        {MODES.map((m) => {
          const allowed = view.allowed_modes.includes(m);
          return (
            <label key={m} className={`flex items-start gap-2 text-sm ${allowed ? "" : "opacity-50"}`}>
              <input
                type="radio"
                name="ai-data-mode"
                value={m}
                checked={view.mode === m}
                disabled={!allowed}
                onChange={() => void choose(m)}
                className="mt-1"
              />
              <span>
                <span className="font-medium">{a.modes[m].label}</span>
                <span className="block text-muted-foreground">{a.modes[m].hint}</span>
                {!allowed && <span className="block text-xs text-muted-foreground">{a.notAllowed}</span>}
              </span>
            </label>
          );
        })}
        {view.choice_capped && <p className="text-sm text-amber-700">{a.capped}</p>}
        {view.organisation_choice !== null && (
          <button type="button" className="text-sm underline" onClick={() => void choose(null)}>{a.useDefault}</button>
        )}
        {note && <p role="status" className="text-sm">{note}</p>}
      </fieldset>

      <div className="space-y-1">
        <h3 className="text-sm font-medium">{a.categoriesTitle}</h3>
        <ul className="space-y-1 text-sm">
          {view.categories.map((c) => (
            <li key={c.key} className="flex flex-wrap justify-between gap-2">
              <span>{a.categories[c.key] ?? c.key}</span>
              <span className={c.state === "not_sent" ? "text-emerald-700" : c.state === "sent" ? "text-amber-700" : ""}>
                {a.states[c.state]}
              </span>
            </li>
          ))}
        </ul>
        {view.document_text === "never" && <p className="text-xs text-muted-foreground">{a.documentNever}</p>}
      </div>

      <div className="space-y-1 text-sm">
        <h3 className="font-medium">{a.usageTitle.replace("{days}", String(view.usage.days))}</h3>
        <p>{a.usage.replace("{calls}", view.usage.calls.toLocaleString(locale)).replace("{size}", formatBytes(view.usage.bytes_out, locale))}</p>
        <p className="text-xs text-muted-foreground">{a.usageNote}</p>
        {view.usage.refused_total > 0 && (
          <p className="text-amber-700">
            {a.refused
              .replace("{n}", view.usage.refused_total.toLocaleString(locale))
              .replace("{context}", String(view.usage.refused.no_organisation_context ?? 0))
              .replace("{dictionary}", String(view.usage.refused.dictionary_unavailable ?? 0))}
          </p>
        )}
        {view.embeddings.pending_reindex > 0 && (
          <p className="text-xs text-muted-foreground">
            {a.reindexPending.replace("{n}", view.embeddings.pending_reindex.toLocaleString(locale))}
          </p>
        )}
        {view.dictionary && (
          <p className="text-xs text-muted-foreground">
            {a.dictionary.replace("{n}", String(view.dictionary.known_names))}
            {view.dictionary.truncated && ` ${a.dictionaryTruncated}`}
            {!view.dictionary.complete && ` ${a.dictionaryIncomplete}`}
          </p>
        )}
      </div>

      <p className="rounded-md bg-muted p-3 text-sm">{a.residual}</p>
    </section>
  );
}

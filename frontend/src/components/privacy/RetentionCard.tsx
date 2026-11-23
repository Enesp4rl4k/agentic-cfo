"use client";

import { useState } from "react";
import { apiClient } from "@/lib/api/client";
import { useI18n } from "@/hooks/useI18n";
import type { RetentionView } from "./types";

/** The retention periods: the platform's defaults, and the owner's own (shorter) choices for the company. */
export function RetentionCard({ view, onChanged }: { view: RetentionView; onChanged: () => void }) {
  const { t } = useI18n();
  const r = t.settingsPrivacy.retention;
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(view.company_keys.map((k) => [k, view.company_choice[k] === undefined ? "" : String(view.company_choice[k])])),
  );
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setNote(null);
    const policy: Record<string, number | null> = {};
    for (const key of view.company_keys) {
      const raw = (draft[key] ?? "").trim();
      policy[key] = raw === "" ? null : Number(raw);
    }
    try {
      await apiClient.put("/privacy/retention", { policy });
      setNote(r.saved);
      onChanged();
    } catch {
      setNote(r.failed);
    } finally {
      setBusy(false);
    }
  }

  const platformOnly = Object.keys(view.platform).filter((k) => !view.company_keys.includes(k));

  return (
    <section className="space-y-3 rounded-lg border border-border p-4" aria-labelledby="privacy-retention">
      <h2 id="privacy-retention" className="text-lg font-semibold">{r.title}</h2>
      <p className="text-sm text-muted-foreground">{r.intro}</p>
      <p className="text-sm">{view.dry_run ? r.dryRunOn : r.dryRunOff}</p>
      <ul className="space-y-3">
        {view.company_keys.map((key) => (
          <li key={key} className="space-y-1">
            <label className="text-sm font-medium" htmlFor={`ret-${key}`}>{r.labels[key] ?? key}</label>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">{r.platform}: {view.platform[key]} {r.unit}</span>
              <input
                id={`ret-${key}`}
                type="number"
                min={0}
                inputMode="numeric"
                disabled={!view.can_edit}
                value={draft[key] ?? ""}
                placeholder={String(view.platform[key] ?? "")}
                onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                className="w-24 rounded-md border border-border bg-background px-2 py-1"
                aria-label={`${r.labels[key] ?? key} (${r.yours})`}
              />
              <span className="text-muted-foreground">{r.unit}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              {r.floor.replace("{n}", String(view.floor_days))} · {r.keep}
            </p>
          </li>
        ))}
        {platformOnly.map((key) => (
          <li key={key} className="text-sm">
            <span className="font-medium">{r.labels[key] ?? key}</span>{" "}
            <span className="text-muted-foreground">{view.platform[key]} {r.unit}</span>
          </li>
        ))}
      </ul>
      {view.can_edit && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => void save()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {busy ? r.saving : r.save}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setDraft(Object.fromEntries(view.company_keys.map((k) => [k, ""])))}
            className="text-sm underline"
          >
            {r.reset}
          </button>
          {note && <p role="status" className="text-sm">{note}</p>}
        </div>
      )}
    </section>
  );
}

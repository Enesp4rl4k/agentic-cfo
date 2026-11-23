"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { useI18n } from "@/hooks/useI18n";
import { CompanyPrivacy } from "./CompanyPrivacy";
import { RetentionCard } from "./RetentionCard";
import { detailOf, downloadBlob, type NoticeStatus, type PrivacyOverview } from "./types";

/** Settings > Veri ve gizlilik. One call (`GET /privacy/overview`) feeds every section. */
export function PrivacyPanel() {
  const { t, locale } = useI18n();
  const p = t.settingsPrivacy;
  const [data, setData] = useState<PrivacyOverview | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get("/privacy/overview");
      setData(res.data?.data as PrivacyOverview);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) return <p role="alert" className="p-6 text-sm text-destructive">{p.loadFailed}</p>;
  if (!data) return <p role="status" className="p-6 text-sm">{p.loading}</p>;

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6 lg:p-8">
      <div>
        <h1 className="text-2xl font-bold">{p.title}</h1>
        <p className="text-sm text-muted-foreground">{p.subtitle}</p>
      </div>
      <Notices
        notices={[["privacy_notice", p.notices.privacyNotice, data.notices.privacy_notice], ["terms", p.notices.terms, data.notices.terms]]}
        locale={locale}
        onAccepted={() => void load()}
      />
      <MyData coolingOffDays={data.cooling_off_days} locale={locale} />
      <CompanyPrivacy isOwner={data.role === "owner"} initialExport={data.export} coolingOffDays={data.cooling_off_days} />
      <section className="space-y-3 rounded-lg border border-border p-4" aria-labelledby="privacy-third">
        <h2 id="privacy-third" className="text-lg font-semibold">{p.thirdParties.title}</h2>
        <p className="text-sm text-muted-foreground">{p.thirdParties.intro}</p>
        <ul className="space-y-3">
          {data.third_parties.map((tp) => (
            <li key={tp.key} className="space-y-1 text-sm">
              <p className="font-medium">{tp.name}</p>
              <p>{tp.sends}</p>
              <p className={tp.masked ? "text-emerald-700" : "text-amber-700"}>{tp.masked ? p.thirdParties.masked : p.thirdParties.notMasked}</p>
              {tp.reaches_from.length > 0 && (
                <p className="text-xs text-muted-foreground">{p.thirdParties.reaches}: {tp.reaches_from.join(", ")}</p>
              )}
            </li>
          ))}
        </ul>
      </section>
      <RetentionCard view={data.retention} onChanged={() => void load()} />
    </main>
  );
}

function Notices({ notices, locale, onAccepted }: {
  notices: [string, string, NoticeStatus][];
  locale: string;
  onAccepted: () => void;
}) {
  const { t } = useI18n();
  const n = t.settingsPrivacy.notices;
  const [busy, setBusy] = useState(false);
  const pending = notices.filter(([, , s]) => s.must_accept);

  async function accept() {
    setBusy(true);
    try {
      const body: Record<string, string> = {};
      for (const [key, , s] of pending) body[key] = s.version;
      await apiClient.post("/privacy/notices/accept", body);
      onAccepted();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-border p-4" aria-labelledby="privacy-notices">
      <h2 id="privacy-notices" className="text-lg font-semibold">{n.title}</h2>
      <p className="text-sm text-muted-foreground">{n.intro}</p>
      <ul className="space-y-2 text-sm">
        {notices.map(([key, label, s]) => (
          <li key={key} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{label}</span>
            <span className="text-muted-foreground">{n.version.replace("{v}", s.version)}</span>
            {s.url ? <a href={s.url} className="underline" target="_blank" rel="noreferrer">{n.openText}</a> : <span className="text-muted-foreground">{n.noLink}</span>}
            {s.must_accept
              ? <span className="text-amber-700">{n.mustAccept}</span>
              : s.accepted_at && <span className="text-muted-foreground">{n.acceptedOn.replace("{date}", new Date(s.accepted_at).toLocaleDateString(locale))}</span>}
          </li>
        ))}
      </ul>
      {pending.length > 0 && (
        <button type="button" disabled={busy} onClick={() => void accept()} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          {busy ? n.saving : n.accept}
        </button>
      )}
    </section>
  );
}

function MyData({ coolingOffDays, locale }: { coolingOffDays: number; locale: string }) {
  const { t } = useI18n();
  const m = t.settingsPrivacy.mine;
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setNote(null);
    try {
      await downloadBlob((path, cfg) => apiClient.get(path, cfg), "/privacy/my-data", "my-data.json");
    } catch {
      setNote(m.downloadFailed);
    } finally {
      setBusy(false);
    }
  }

  async function erase() {
    setBusy(true);
    setNote(null);
    try {
      const res = await apiClient.post("/privacy/member-erasure", { confirmation: email });
      const when = (res.data?.data as { execute_after?: string | null })?.execute_after;
      setNote(m.scheduled.replace("{date}", when ? new Date(when).toLocaleDateString(locale) : ""));
    } catch (e) {
      const detail = detailOf(e) ?? "";
      setNote(detail.startsWith("sole_owner") ? m.soleOwner : detail.startsWith("wrong_email") ? m.wrongEmail : m.failed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4 rounded-lg border border-border p-4" aria-labelledby="privacy-mine">
      <h2 id="privacy-mine" className="text-lg font-semibold">{m.title}</h2>
      <p className="text-sm text-muted-foreground">{m.intro}</p>
      <button type="button" disabled={busy} onClick={() => void download()} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
        {busy ? m.downloading : m.download}
      </button>
      <div className="space-y-2">
        <h3 className="font-medium">{m.deleteTitle}</h3>
        <p className="text-sm text-muted-foreground">{m.deleteIntro.replace("{days}", String(coolingOffDays))}</p>
        <label className="text-sm font-medium" htmlFor="erase-me-email">{m.emailLabel}</label>
        <input
          id="erase-me-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="off"
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
        <button type="button" disabled={busy || email.trim() === ""} onClick={() => void erase()} className="rounded-lg border border-destructive px-4 py-2 text-sm font-semibold text-destructive disabled:opacity-50">
          {busy ? m.working : m.deleteButton}
        </button>
      </div>
      {note && <p role="status" className="text-sm">{note}</p>}
    </section>
  );
}

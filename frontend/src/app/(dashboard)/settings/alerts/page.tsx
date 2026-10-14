"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { useI18n } from "@/hooks/useI18n";

type Prefs = {
  slack_webhook_url?: string;
  email_recipients?: string;
  enabled?: boolean;
};

export default function AlertsSettingsPage() {
  const { t } = useI18n();
  const a = t.settingsAlerts;
  const [prefs, setPrefs] = useState<Prefs>({ enabled: true });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.get("/alerts/preferences").catch(() => null);
        const data = res?.data?.data ?? res?.data;
        if (!cancelled && data) setPrefs(data as Prefs);
      } catch {
        /* endpoint may be optional */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      await apiClient.put("/alerts/preferences", prefs);
      setMessage(a.saved);
    } catch (e) {
      // Fallback: store locally if API missing
      try {
        localStorage.setItem("alert_prefs", JSON.stringify(prefs));
        setMessage(a.savedLocal);
      } catch {
        setError(e instanceof Error ? e.message : a.saveFailed);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto max-w-xl space-y-6 p-4 sm:p-6 lg:p-8">
      <div>
        <h1 className="text-2xl font-bold">{a.title}</h1>
        <p className="text-sm text-muted-foreground">
          {a.subtitle}
        </p>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(prefs.enabled)}
          onChange={(e) => setPrefs((p) => ({ ...p, enabled: e.target.checked }))}
        />
        {a.enable}
      </label>

      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor="slack">{a.slackLabel}</label>
        <input
          id="slack"
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          value={prefs.slack_webhook_url ?? ""}
          onChange={(e) => setPrefs((p) => ({ ...p, slack_webhook_url: e.target.value }))}
          placeholder={a.slackPlaceholder}
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor="email">{a.emailLabel}</label>
        <input
          id="email"
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          value={prefs.email_recipients ?? ""}
          onChange={(e) => setPrefs((p) => ({ ...p, email_recipients: e.target.value }))}
          placeholder={a.emailPlaceholder}
        />
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {message && <p className="text-sm text-emerald-600">{message}</p>}

      <button
        type="button"
        disabled={saving}
        onClick={() => void save()}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
      >
        {saving ? a.saving : a.save}
      </button>
    </main>
  );
}

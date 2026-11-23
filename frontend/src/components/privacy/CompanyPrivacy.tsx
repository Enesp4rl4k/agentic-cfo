"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { useI18n } from "@/hooks/useI18n";
import { ErasureStates } from "./ErasureStates";
import { downloadBlob, type ErasureRequestRow, type ExportState } from "./types";

type Props = { isOwner: boolean; initialExport: ExportState | null; coolingOffDays: number; supportContact: string | null };

/** Owner-only: the company export (a job) and the erasure request with its cooling-off and its cancel. */
export function CompanyPrivacy({ isOwner, initialExport, coolingOffDays, supportContact }: Props) {
  const { t, locale } = useI18n();
  const c = t.settingsPrivacy.company;
  const [exp, setExp] = useState<ExportState | null>(initialExport);
  const [requests, setRequests] = useState<ErasureRequestRow[]>([]);
  const [phrase, setPhrase] = useState<{ id: string; text: string } | null>(null);
  const [typed, setTyped] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(locale) : "");

  const loadRequests = useCallback(async () => {
    try {
      const res = await apiClient.get("/privacy/erasure-requests");
      setRequests((res.data?.data?.requests ?? []) as ErasureRequestRow[]);
    } catch {
      setRequests([]);
    }
  }, []);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  // While the bundle is being built, ask again every few seconds.
  useEffect(() => {
    if (!exp || (exp.status !== "queued" && exp.status !== "running")) return;
    const id = window.setInterval(() => {
      void apiClient.get(`/privacy/exports/${exp.export_id}`).then((res) => setExp(res.data?.data as ExportState)).catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(id);
  }, [exp]);

  async function requestExport() {
    setMessage(null);
    try {
      const res = await apiClient.post("/privacy/exports");
      setExp(res.data?.data as ExportState);
    } catch {
      setMessage(c.exportFailedRequest);
    }
  }

  async function startErasure() {
    setMessage(null);
    try {
      const res = await apiClient.post("/compliance/org-erasure/request", { mode: "anonymise" });
      const d = res.data?.data as { request_id: string; confirmation_phrase: string };
      setPhrase({ id: d.request_id, text: d.confirmation_phrase });
      setTyped("");
    } catch {
      setMessage(c.eraseFailed);
    }
  }

  async function confirmErasure() {
    if (!phrase) return;
    try {
      const res = await apiClient.post(`/compliance/org-erasure/${phrase.id}/confirm`, { confirmation_phrase: typed });
      const d = res.data?.data as { execute_after?: string | null };
      setMessage(c.eraseScheduled.replace("{date}", day(d.execute_after ?? null)));
      setPhrase(null);
      await loadRequests();
    } catch {
      setMessage(c.eraseFailed);
    }
  }

  async function cancel(row: ErasureRequestRow) {
    const path = row.scope === "org" ? `/compliance/org-erasure/${row.request_id}/cancel` : `/privacy/member-erasure/${row.request_id}/cancel`;
    try {
      await apiClient.post(path);
      await loadRequests();
    } catch {
      setMessage(c.eraseFailed);
    }
  }

  if (!isOwner) {
    return (
      <section className="rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold">{c.title}</h2>
        <p className="text-sm text-muted-foreground">{c.ownerOnly}</p>
      </section>
    );
  }

  const working = exp?.status === "queued" || exp?.status === "running";
  return (
    <section className="space-y-6 rounded-lg border border-border p-4" aria-labelledby="privacy-company">
      <h2 id="privacy-company" className="text-lg font-semibold">{c.title}</h2>

      <div className="space-y-2">
        <h3 className="font-medium">{c.exportTitle}</h3>
        <p className="text-sm text-muted-foreground">{c.exportIntro}</p>
        {working && <p role="status" className="text-sm">{c.exportWorking}</p>}
        {exp?.status === "failed" && <p role="alert" className="text-sm text-destructive">{c.exportFailed}</p>}
        {exp?.status === "ready" && (
          <p className="text-sm">
            {c.exportReady.replace("{date}", day(exp.expires_at))}{" "}
            <button
              type="button"
              className="underline"
              onClick={() => void downloadBlob((p, cfg) => apiClient.get(p, cfg), `/privacy/exports/${exp.export_id}/download`, "company-export.zip").catch(() => setMessage(c.exportFailed))}
            >
              {c.exportDownload}
            </button>
          </p>
        )}
        {!working && exp?.status !== "ready" && (
          <button type="button" onClick={() => void requestExport()} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">
            {c.exportRequest}
          </button>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="font-medium">{c.eraseTitle}</h3>
        <p className="text-sm text-muted-foreground">{c.eraseIntro.replace("{days}", String(coolingOffDays))}</p>
        {requests.length > 0 && <ErasureStates rows={requests} supportContact={supportContact} day={day} onCancel={(row) => void cancel(row)} />}
        {phrase ? (
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="erase-phrase">{c.erasePhrase.replace("{phrase}", phrase.text)}</label>
            <input
              id="erase-phrase"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              autoComplete="off"
            />
            <button type="button" disabled={typed.trim() !== phrase.text} onClick={() => void confirmErasure()} className="rounded-lg bg-destructive px-4 py-2 text-sm font-semibold text-destructive-foreground disabled:opacity-50">
              {c.eraseConfirm}
            </button>
          </div>
        ) : (
          <button type="button" onClick={() => void startErasure()} className="rounded-lg border border-destructive px-4 py-2 text-sm font-semibold text-destructive">
            {c.eraseRequest}
          </button>
        )}
      </div>
      {message && <p role="status" className="text-sm">{message}</p>}
    </section>
  );
}

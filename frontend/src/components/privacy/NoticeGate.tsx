"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { signOut, useSession } from "next-auth/react";
import { apiClient } from "@/lib/api/client";
import { useI18n } from "@/hooks/useI18n";
import { NoticePrompt } from "./NoticePrompt";
import { statusOf, type NoticesState } from "./types";

type Load = { kind: "loading" } | { kind: "failed" } | { kind: "ready"; notices: NoticesState };

/**
 * Wraps the signed-in app. The server says which CURRENT notice versions this person has not accepted
 * (`GET /privacy/notices`, the same state the settings screen reads); while any is pending the app is not rendered at
 * all, only the prompt (and a sign-out). Acceptance goes through `POST /privacy/notices/accept`, which records only
 * versions the server currently publishes. A failed read does not open the app: it offers a retry and the sign-out.
 */
export function NoticeGate({ children }: { children: ReactNode }) {
  const { status } = useSession();
  const { t } = useI18n();
  const g = t.noticeGate;
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const read = useCallback(async () => {
    setLoad({ kind: "loading" });
    try {
      const res = await apiClient.get("/privacy/notices");
      setLoad({ kind: "ready", notices: res.data?.data as NoticesState });
    } catch {
      setLoad({ kind: "failed" });
    }
  }, []);

  useEffect(() => {
    if (status === "authenticated") void read();
  }, [status, read]);

  const leave = () => void signOut({ callbackUrl: "/auth/login" });

  if (status === "unauthenticated") return <>{children}</>; // the sign-in redirect is not this component's job
  if (status === "loading" || load.kind === "loading") {
    return <p role="status" className="p-6 text-sm text-muted-foreground">{g.loading}</p>;
  }
  if (load.kind === "failed") {
    return (
      <div className="mx-auto max-w-md space-y-3 p-6">
        <p role="alert" className="text-sm">{g.loadFailed}</p>
        <div className="flex gap-2">
          <button type="button" onClick={() => void read()} className="min-h-[44px] rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">{g.retry}</button>
          <button type="button" onClick={leave} className="min-h-[44px] rounded-lg border border-border px-4 text-sm font-medium">{g.signOut}</button>
        </div>
      </div>
    );
  }

  const { notices } = load;
  if (!notices.must_accept) return <>{children}</>;

  const labels = t.settingsPrivacy.notices;
  const pending = [
    { key: "privacy_notice", label: labels.privacyNotice, status: notices.privacy_notice },
    { key: "terms", label: labels.terms, status: notices.terms },
  ].filter((n) => n.status.must_accept);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      // Exactly the versions the screen showed; the server refuses any that is no longer the current one.
      const body: Record<string, string> = {};
      for (const n of pending) body[n.key] = n.status.version;
      const res = await apiClient.post("/privacy/notices/accept", body);
      const next = (res.data?.data as { notices?: NoticesState } | undefined)?.notices;
      if (next) setLoad({ kind: "ready", notices: next });
      else await read();
    } catch (e) {
      const stale = statusOf(e) === 409; // the server refuses a version that is not the current one
      setError(stale ? g.stale : g.acceptFailed);
      if (stale) await read(); // a new version was published meanwhile: show it, do not record the old one
    } finally {
      setBusy(false);
    }
  }

  return <NoticePrompt pending={pending} busy={busy} error={error} onAccept={() => void accept()} onSignOut={leave} />;
}

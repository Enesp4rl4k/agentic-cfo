"use client";

import { useEffect, useRef } from "react";
import { Logo } from "@/components/ui/logo";
import { useI18n } from "@/hooks/useI18n";
import type { NoticeStatus } from "./types";

export type PendingNotice = { key: string; label: string; status: NoticeStatus };

type Props = {
  pending: PendingNotice[];
  busy: boolean;
  error: string | null;
  onAccept: () => void;
  onSignOut: () => void;
};

/**
 * The blocking prompt shown after sign-in while a CURRENT notice version is not accepted (see `NoticeGate`).
 * It shows what the server says: title, version, a link to the full text. Nothing is pre-ticked, there is no close
 * button and no accept-by-dismissal: the only ways out are the explicit accept button and signing out.
 */
export function NoticePrompt({ pending, busy, error, onAccept, onSignOut }: Props) {
  const { t } = useI18n();
  const g = t.noticeGate;
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="notice-gate-title"
        aria-describedby="notice-gate-intro"
        className="w-full max-w-lg space-y-5 rounded-xl border border-border bg-card p-5 shadow-sm sm:p-7"
      >
        <div className="flex justify-center"><Logo size="md" /></div>
        <div className="space-y-2">
          <h1 id="notice-gate-title" ref={heading} tabIndex={-1} className="text-xl font-bold outline-none">{g.title}</h1>
          <p id="notice-gate-intro" className="text-sm text-muted-foreground">{g.intro}</p>
        </div>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {pending.map(({ key, label, status }) => (
            <li key={key} className="space-y-1 p-3.5 text-sm">
              <p className="font-semibold">{label}</p>
              <p className="text-xs text-muted-foreground">{g.version.replace("{v}", status.version)}</p>
              {status.url ? (
                <a href={status.url} target="_blank" rel="noreferrer" className="inline-flex min-h-[44px] items-center font-medium text-primary underline underline-offset-4">
                  {g.open}
                </a>
              ) : (
                <p className="text-xs text-amber-700">{g.noLink}</p>
              )}
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">{g.consequence}</p>
        {error && <p role="alert" className="rounded-lg border border-destructive/20 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</p>}
        <div className="flex flex-col gap-2 sm:flex-row-reverse">
          <button
            type="button"
            disabled={busy}
            onClick={onAccept}
            className="min-h-[44px] flex-1 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {busy ? g.accepting : g.accept}
          </button>
          <button
            type="button"
            onClick={onSignOut}
            className="min-h-[44px] flex-1 rounded-lg border border-border px-4 text-sm font-medium hover:bg-muted"
          >
            {g.signOut}
          </button>
        </div>
      </div>
    </div>
  );
}

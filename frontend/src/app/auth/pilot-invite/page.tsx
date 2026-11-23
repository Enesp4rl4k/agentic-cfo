"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { useI18n } from "@/hooks/useI18n";
import { APP_HOME } from "@/lib/routes";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Preview =
  | { state: "unknown" }
  | { state: "valid" | "used" | "expired"; email: string; company_name: string | null; registration_closed: boolean };

type Load = { kind: "loading" } | { kind: "failed" } | { kind: "ready"; preview: Preview };

const inputClass = cn(
  "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 text-sm",
  "placeholder:text-muted-foreground",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
);

/**
 * The page the operator's pilot invitation e-mail links to: `/auth/pilot-invite?token=…`.
 *
 * The one way a new company gets in: the invited person chooses a name and a password and becomes the
 * owner of a new company named in the invitation (`POST /auth/register` with the token), then is signed in.
 * The address is the one the invitation names; it cannot be changed here.
 */
function PilotInvite() {
  const { t } = useI18n();
  const s = t.pilotInvite;
  const token = useSearchParams().get("token") ?? "";

  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setLoad({ kind: "ready", preview: { state: "unknown" } });
      return;
    }
    let cancelled = false;
    fetch(`${API_BASE}/api/v1/pilot/invite/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok || !body?.data) throw new Error("preview");
        if (!cancelled) setLoad({ kind: "ready", preview: body.data as Preview });
      })
      .catch(() => {
        if (!cancelled) setLoad({ kind: "failed" });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function submit(e: FormEvent, email: string) {
    e.preventDefault();
    if (password.length < 8) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, invite_token: token, ...(fullName.trim() ? { full_name: fullName.trim() } : {}) }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(body?.error ?? body?.detail ?? s.failed);
        return;
      }
      const result = await signIn("credentials", { email, password, redirect: false });
      if (result?.error) throw new Error("sign-in");
      window.location.assign(APP_HOME);
    } catch {
      setError(s.failed);
    } finally {
      setBusy(false);
    }
  }

  function notice(title: string, body: string) {
    return (
      <div role="status" className="space-y-3 rounded-lg border border-border bg-muted/30 p-5">
        <h1 className="m-0 text-lg font-semibold">{title}</h1>
        <p className="m-0 text-sm text-muted-foreground">{body}</p>
        <Link href="/auth/login" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
          {s.signIn}
        </Link>
      </div>
    );
  }

  function content() {
    if (load.kind === "loading") {
      return (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {s.loading}
        </p>
      );
    }
    if (load.kind === "failed") return notice(s.title, s.loadFailed);
    const preview = load.preview;
    if (preview.state === "unknown") return notice(s.unknownTitle, s.unknownBody);
    if (preview.state === "expired") return notice(s.expiredTitle, s.expiredBody);
    if (preview.state === "used") return notice(s.usedTitle, s.usedBody);
    if (preview.registration_closed) return notice(s.title, s.closedBody);
    return (
      <form onSubmit={(e) => submit(e, preview.email)} className="space-y-4">
        <div>
          <h1 className="m-0 text-2xl font-bold tracking-tight">{s.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {s.invitedTo.replace("{company}", preview.company_name ?? "")}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{s.forAddress.replace("{email}", preview.email)}</p>
        </div>
        {error && (
          <div role="alert" className="rounded-lg border border-destructive/20 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">
            {error}
          </div>
        )}
        <div className="space-y-1.5">
          <label htmlFor="fullName" className="text-xs font-medium text-foreground/80">
            {s.fullName}
          </label>
          <input id="fullName" type="text" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} className={inputClass} />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="password" className="text-xs font-medium text-foreground/80">
            {s.password}
          </label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={s.passwordHint}
            className={inputClass}
          />
        </div>
        <button
          type="submit"
          disabled={busy || password.length < 8}
          className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60"
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          {busy ? s.submitting : s.submit}
        </button>
      </form>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex justify-center">
          <Logo size="lg" />
        </div>
        {content()}
      </div>
    </div>
  );
}

export default function PilotInvitePage() {
  return (
    <Suspense fallback={null}>
      <PilotInvite />
    </Suspense>
  );
}

"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Dead = "invalid" | "expired" | "used";
type Phase =
  | { kind: "reading" }
  | { kind: "verifying" }
  | { kind: "success" }
  | { kind: "dead"; why: Dead }
  | { kind: "failed" }
  | { kind: "resend" };

/** The token of the e-mailed link, taken out of the address bar (`#token=…`, or a hand-copied `?token=`). */
function takeToken(): string {
  const fromFragment = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
  const fromQuery = new URLSearchParams(window.location.search).get("token");
  if (fromFragment !== null || fromQuery !== null) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  return fromFragment ?? fromQuery ?? "";
}

/**
 * `/auth/verify-email`: opens the e-mailed link and verifies the address. A new account cannot sign in
 * before this. Without a token the page is the "send me the link again" form, which answers the same
 * for every address.
 */
export default function VerifyEmailPage() {
  const { t } = useI18n();
  const s = t.emailVerification;
  const [phase, setPhase] = useState<Phase>({ kind: "reading" });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = takeToken();
    if (!token) {
      setPhase({ kind: "resend" });
      return;
    }
    setPhase({ kind: "verifying" });
    fetch(`${API_BASE}/api/v1/auth/verify-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        if (res.ok) {
          setPhase({ kind: "success" });
          return;
        }
        const body = await res.json().catch(() => null);
        const state = body?.data?.state;
        setPhase(
          res.status === 400 && (state === "invalid" || state === "expired" || state === "used")
            ? { kind: "dead", why: state }
            : { kind: "failed" },
        );
      })
      .catch(() => setPhase({ kind: "failed" }));
  }, []);

  async function resend(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/resend-verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      if (res.status === 429) setError(s.tooMany);
      else if (!res.ok) setError(s.failed);
      else setSent(true);
    } catch {
      setError(s.failed);
    } finally {
      setBusy(false);
    }
  }

  function resendForm() {
    if (sent) {
      return <Notice title={s.sentTitle} body={s.sentBody} role="status" />;
    }
    return (
      <form onSubmit={(e) => void resend(e)} className="space-y-4" noValidate>
        <p className="m-0 text-sm text-muted-foreground">{s.resendLead}</p>
        {error && (
          <div role="alert" className="rounded-lg border border-destructive/20 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive">
            {error}
          </div>
        )}
        <div className="space-y-1.5">
          <label htmlFor="email" className="text-xs font-medium text-foreground/80">{s.email}</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={cn(
              "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 text-sm",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
            )}
          />
        </div>
        <button
          type="submit"
          disabled={busy || !email.trim()}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50"
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          {busy ? s.sending : s.resend}
        </button>
      </form>
    );
  }

  function body() {
    switch (phase.kind) {
      case "reading":
      case "verifying":
        return (
          <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {s.verifying}
          </p>
        );
      case "success":
        return (
          <Notice title={s.successTitle} body={s.successBody} role="status">
            <Link href="/auth/login" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
              {s.signIn}
            </Link>
          </Notice>
        );
      case "dead": {
        const text = {
          invalid: [s.invalidTitle, s.invalidBody],
          expired: [s.expiredTitle, s.expiredBody],
          used: [s.usedTitle, s.usedBody],
        }[phase.why];
        return (
          <div className="space-y-4">
            <Notice title={text[0]} body={text[1]}>
              {phase.why === "used" && (
                <Link href="/auth/login" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
                  {s.signIn}
                </Link>
              )}
            </Notice>
            {phase.why !== "used" && resendForm()}
          </div>
        );
      }
      case "failed":
        return <Notice title={s.failedTitle} body={s.failed} />;
      case "resend":
        return resendForm();
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-12">
      <div className="mb-6 flex justify-center">
        <Link href="/" className="rounded-md text-foreground"><Logo size="lg" /></Link>
      </div>
      <h1 className="mb-5 text-center text-2xl font-bold tracking-tight">{s.title}</h1>
      {body()}
    </main>
  );
}

function Notice({ title, body, children, role = "alert" }: { title: string; body: string; children?: ReactNode; role?: "alert" | "status" }) {
  return (
    <div role={role} className="space-y-2 rounded-lg border border-border bg-muted/30 p-4">
      <p className="m-0 text-sm font-semibold">{title}</p>
      <p className="m-0 text-sm text-muted-foreground">{body}</p>
      {children}
    </div>
  );
}

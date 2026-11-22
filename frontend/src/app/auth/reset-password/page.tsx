"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const MIN_LENGTH = 8;

type Dead = "invalid" | "expired" | "used";
type Phase =
  | { kind: "reading" }
  | { kind: "form" }
  | { kind: "success" }
  | { kind: "dead"; why: Dead };

/**
 * Read the token the e-mail link carries and take it out of the address bar.
 *
 * The link is `/auth/reset-password#token=…`: a fragment is never sent to any server. A `?token=`
 * is read too (a link copied by hand), and either way the address is rewritten at once so the
 * token is not in the history entry, a screenshot, or a Referer. Nothing else puts it in a URL:
 * it goes to the API in a POST body.
 */
function takeToken(): string {
  const fromFragment = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
  const fromQuery = new URLSearchParams(window.location.search).get("token");
  const token = fromFragment ?? fromQuery ?? "";
  if (fromFragment !== null || fromQuery !== null) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  return token;
}

const inputClass = cn(
  "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 text-sm",
  "placeholder:text-muted-foreground",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
);

/** `/auth/reset-password`: choose a new password with the e-mailed single-use token. */
export default function ResetPasswordPage() {
  const { t } = useI18n();
  const s = t.passwordReset.reset;
  const [token, setToken] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "reading" });
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const found = takeToken();
    setToken(found);
    setPhase(found ? { kind: "form" } : { kind: "dead", why: "invalid" });
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== repeat) {
      setError(s.mismatch);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (res.ok) {
        setToken("");
        setPhase({ kind: "success" });
        return;
      }
      if (res.status === 429) {
        setError(s.tooMany);
        return;
      }
      const body = await res.json().catch(() => null);
      const state = body?.data?.state;
      if (res.status === 400 && (state === "invalid" || state === "expired" || state === "used")) {
        setPhase({ kind: "dead", why: state });
        return;
      }
      setError(s.failed);
    } catch {
      setError(s.failed);
    } finally {
      setBusy(false);
    }
  }

  function body() {
    if (phase.kind === "reading") {
      return (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        </p>
      );
    }
    if (phase.kind === "success") {
      return (
        <Notice title={s.successTitle} body={s.successBody} role="status">
          <Link href="/auth/login" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
            {s.signIn}
          </Link>
        </Notice>
      );
    }
    if (phase.kind === "dead") {
      const text = {
        invalid: [s.invalidTitle, s.invalidBody],
        expired: [s.expiredTitle, s.expiredBody],
        used: [s.usedTitle, s.usedBody],
      }[phase.why];
      return (
        <Notice title={text[0]} body={text[1]}>
          <Link href="/auth/forgot-password" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
            {s.requestNew}
          </Link>
        </Notice>
      );
    }
    return (
      <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
        <p className="m-0 text-sm text-muted-foreground">{s.lead}</p>
        {error && (
          <div role="alert" className="rounded-lg border border-destructive/20 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive">
            {error}
          </div>
        )}
        <div className="space-y-1.5">
          <label htmlFor="new-password" className="text-xs font-medium text-foreground/80">{s.newPassword}</label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={MIN_LENGTH}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
          <p className="m-0 text-xs text-muted-foreground">{s.passwordHint}</p>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="repeat-password" className="text-xs font-medium text-foreground/80">{s.confirm}</label>
          <input
            id="repeat-password"
            type="password"
            autoComplete="new-password"
            required
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            className={inputClass}
          />
        </div>
        <button
          type="submit"
          disabled={busy || password.length < MIN_LENGTH || repeat.length === 0}
          className={cn(
            "flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground",
            "transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50",
          )}
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          {busy ? s.submitting : s.submit}
        </button>
      </form>
    );
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

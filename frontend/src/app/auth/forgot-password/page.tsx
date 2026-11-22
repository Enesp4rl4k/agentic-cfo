"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Ask for a password-reset link: `POST /auth/forgot-password`.
 *
 * The API answers every address the same way (known, unknown, deactivated, SSO-only), so the page
 * does too: whatever the address, a successful request shows the same "check your e-mail" text and
 * never says whether an account exists.
 */
export default function ForgotPasswordPage() {
  const { t } = useI18n();
  const s = t.passwordReset.forgot;
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/forgot-password`, {
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

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-12">
      <div className="mb-6 flex justify-center">
        <Link href="/" className="rounded-md text-foreground"><Logo size="lg" /></Link>
      </div>
      <h1 className="mb-5 text-center text-2xl font-bold tracking-tight">{s.title}</h1>

      {sent ? (
        <div role="status" className="space-y-2 rounded-lg border border-border bg-muted/30 p-4">
          <p className="m-0 text-sm font-semibold">{s.sentTitle}</p>
          <p className="m-0 text-sm text-muted-foreground">{s.sentBody}</p>
        </div>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
          <p className="m-0 text-sm text-muted-foreground">{s.lead}</p>
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
                "placeholder:text-muted-foreground",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
              )}
            />
          </div>
          <button
            type="submit"
            disabled={busy || !email.trim()}
            className={cn(
              "flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground",
              "transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50",
            )}
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {busy ? s.submitting : s.submit}
          </button>
        </form>
      )}

      <p className="mt-6 text-center text-sm">
        <Link href="/auth/login" className="font-semibold text-primary underline-offset-4 hover:underline">{s.back}</Link>
      </p>
    </main>
  );
}

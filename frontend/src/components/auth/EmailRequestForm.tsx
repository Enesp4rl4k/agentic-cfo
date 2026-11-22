"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function Notice({
  title, body, children, role = "alert",
}: { title: string; body: string; children?: ReactNode; role?: "alert" | "status" }) {
  return (
    <div role={role} className="space-y-2 rounded-lg border border-border bg-muted/30 p-4">
      <p className="m-0 text-sm font-semibold">{title}</p>
      <p className="m-0 text-sm text-muted-foreground">{body}</p>
      {children}
    </div>
  );
}

export type EmailRequestText = {
  lead: string;
  email: string;
  submit: string;
  submitting: string;
  sentTitle: string;
  sentBody: string;
  tooMany: string;
  failed: string;
};

/**
 * Ask the API to e-mail a link to an address (`forgot-password`, `resend-verification`).
 *
 * Those endpoints answer every address the same way, so the form does too: a successful request
 * always shows the same confirmation and never says whether an account exists.
 */
export function EmailRequestForm({ endpoint, text }: { endpoint: string; text: EmailRequestText }) {
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
      const res = await fetch(`${API_BASE}/api/v1/auth/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      if (res.status === 429) setError(text.tooMany);
      else if (!res.ok) setError(text.failed);
      else setSent(true);
    } catch {
      setError(text.failed);
    } finally {
      setBusy(false);
    }
  }

  if (sent) return <Notice title={text.sentTitle} body={text.sentBody} role="status" />;
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
      <p className="m-0 text-sm text-muted-foreground">{text.lead}</p>
      {error && (
        <div role="alert" className="rounded-lg border border-destructive/20 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive">
          {error}
        </div>
      )}
      <div className="space-y-1.5">
        <label htmlFor="email" className="text-xs font-medium text-foreground/80">{text.email}</label>
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
        {busy ? text.submitting : text.submit}
      </button>
    </form>
  );
}

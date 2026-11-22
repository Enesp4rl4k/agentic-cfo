"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { useI18n } from "@/hooks/useI18n";
import { EmailRequestForm, Notice } from "@/components/auth/EmailRequestForm";

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

  const resendText = {
    lead: s.resendLead, email: s.email, submit: s.resend, submitting: s.sending,
    sentTitle: s.sentTitle, sentBody: s.sentBody, tooMany: s.tooMany, failed: s.failed,
  };
  const resendForm = () => <EmailRequestForm endpoint="resend-verification" text={resendText} />;

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

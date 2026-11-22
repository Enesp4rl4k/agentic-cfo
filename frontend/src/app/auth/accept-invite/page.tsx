"use client";

import { Suspense, useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { useI18n } from "@/hooks/useI18n";
import { APP_HOME } from "@/lib/routes";
import { useCompanyContextStore } from "@/store/companyContext";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Preview =
  | { state: "unknown" }
  | {
      state: "valid" | "used" | "expired";
      email: string;
      role: string;
      org_name: string | null;
      account_exists: boolean;
    };

type Load = { kind: "loading" } | { kind: "failed" } | { kind: "ready"; preview: Preview };

const inputClass = cn(
  "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 text-sm",
  "placeholder:text-muted-foreground",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
);

/**
 * The page the invitation e-mail links to: `/auth/accept-invite?token=…`.
 *
 * The token is read once to say whose invitation it is and what state it is in (valid, used,
 * expired, unknown), before anybody signs in. A valid one is accepted three ways: the person has no
 * account (a name and a password create it), has one (its password proves it), or is already signed
 * in as the invited address (one click). Signed in as somebody else, the page says so and offers to
 * sign out. Accepting adds this company to the person's companies without touching the others, and
 * the page then switches into it, so they land in the company they were invited to.
 */
function AcceptInvite() {
  const { t } = useI18n();
  const s = t.acceptInvite;
  const token = useSearchParams().get("token") ?? "";
  const { data: session, status, update } = useSession();
  const { clearWorkspace } = useCompanyContextStore();

  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [landing, setLanding] = useState(false);

  useEffect(() => {
    if (!token) {
      setLoad({ kind: "ready", preview: { state: "unknown" } });
      return;
    }
    let cancelled = false;
    fetch(`${API_BASE}/api/v1/org/invite/preview`, {
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

  const roleName = (role: string) => (t.orgSwitcher.roles as Record<string, string>)[role] ?? role;

  async function join(e: FormEvent, preview: Extract<Preview, { email: string }>, asSession: boolean) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const accessToken = (session as { accessToken?: string } | null)?.accessToken;
      const res = await fetch(`${API_BASE}/api/v1/org/invite/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(asSession && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}) },
        body: JSON.stringify(asSession ? { token } : { token, password, ...(fullName.trim() ? { full_name: fullName.trim() } : {}) }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(res.status === 401 ? s.wrongPassword : (body?.error ?? body?.detail ?? s.failed));
        return;
      }
      const accepted = body.data as { access_token: string; joined_org_id: string; user: { org_id: string | null } };
      setLanding(true);
      // A person with companies of their own keeps working where they were: take them into this one.
      if (accepted.user.org_id !== accepted.joined_org_id) {
        const switched = await fetch(`${API_BASE}/api/v1/org/switch`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${accepted.access_token}` },
          body: JSON.stringify({ org_id: accepted.joined_org_id }),
        });
        if (!switched.ok) throw new Error("switch");
      }
      if (asSession) {
        await update(); // the cookie still carries the role of the company they were in
      } else {
        const result = await signIn("credentials", { email: preview.email, password, redirect: false });
        if (result?.error) throw new Error("sign-in");
      }
      clearWorkspace();
      window.location.assign(APP_HOME);
    } catch {
      setLanding(false);
      setError(s.failed);
    } finally {
      setBusy(false);
    }
  }

  function renderBody() {
    if (load.kind === "loading" || status === "loading") {
      return (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {s.loading}
        </p>
      );
    }
    if (load.kind === "failed") return <p role="alert" className="text-sm text-destructive">{s.loadFailed}</p>;

    const { preview } = load;
    if (preview.state === "unknown") {
      return <Notice title={s.states.unknownTitle} body={s.states.unknownBody} />;
    }
    if (preview.state === "expired") {
      return <Notice title={s.states.expiredTitle} body={s.states.expiredBody} />;
    }
    if (preview.state === "used") {
      return (
        <Notice title={s.states.usedTitle} body={s.states.usedBody}>
          <Link href="/auth/login" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
            {s.states.signIn}
          </Link>
        </Notice>
      );
    }

    const signedInAs = status === "authenticated" ? (session?.user?.email ?? null) : null;
    const sameAccount = signedInAs !== null && signedInAs.toLowerCase() === preview.email.toLowerCase();
    const header = (
      <div className="space-y-1">
        <p className="m-0 text-sm font-medium">
          {s.invitedTo.replace("{org}", preview.org_name ?? "").replace("{role}", roleName(preview.role))}
        </p>
        <p className="m-0 text-xs text-muted-foreground">{s.forAddress.replace("{email}", preview.email)}</p>
      </div>
    );

    if (signedInAs !== null && !sameAccount) {
      return (
        <div className="space-y-4">
          {header}
          <div role="alert" className="space-y-2 rounded-lg border border-border bg-muted/30 p-3.5">
            <p className="m-0 text-sm font-semibold">{s.wrongAccount.title}</p>
            <p className="m-0 text-sm text-muted-foreground">
              {s.wrongAccount.body.replace("{current}", signedInAs).replace("{email}", preview.email)}
            </p>
            <button
              type="button"
              onClick={() => void signOut({ redirect: false })}
              className="h-9 rounded-lg border border-border bg-card px-3 text-sm font-medium hover:bg-muted"
            >
              {s.wrongAccount.signOut}
            </button>
          </div>
        </div>
      );
    }

    const needsName = !preview.account_exists;
    const lead = sameAccount
      ? s.signedIn.lead.replace("{email}", preview.email)
      : preview.account_exists
        ? s.existing.lead
        : s.created.lead;
    const submitLabel = busy ? (landing ? s.switching : s.joining) : needsName ? s.joinCreate : s.join;

    return (
      <form onSubmit={(e) => void join(e, preview, sameAccount)} className="space-y-4" noValidate>
        {header}
        <p className="m-0 text-sm text-muted-foreground">{lead}</p>
        {error && (
          <div role="alert" className="rounded-lg border border-destructive/20 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive">
            {error}
          </div>
        )}
        {needsName && (
          <div className="space-y-1.5">
            <label htmlFor="fullName" className="text-xs font-medium text-foreground/80">{s.created.fullName}</label>
            <input id="fullName" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} className={inputClass} />
          </div>
        )}
        {!sameAccount && (
          <div className="space-y-1.5">
            <label htmlFor="password" className="text-xs font-medium text-foreground/80">{s.password}</label>
            <input
              id="password"
              type="password"
              autoComplete={needsName ? "new-password" : "current-password"}
              required
              minLength={needsName ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
            {needsName && <p className="m-0 text-xs text-muted-foreground">{s.passwordHint}</p>}
          </div>
        )}
        <button
          type="submit"
          disabled={busy || (!sameAccount && (needsName ? password.length < 8 : password.length === 0))}
          className={cn(
            "flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground",
            "transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50",
          )}
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          {submitLabel}
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
      {renderBody()}
    </main>
  );
}

function Notice({ title, body, children }: { title: string; body: string; children?: ReactNode }) {
  return (
    <div role="alert" className="space-y-2 rounded-lg border border-border bg-muted/30 p-4">
      <p className="m-0 text-sm font-semibold">{title}</p>
      <p className="m-0 text-sm text-muted-foreground">{body}</p>
      {children}
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <AcceptInvite />
    </Suspense>
  );
}

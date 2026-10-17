"use client";

import { useState, FormEvent } from "react";
import { useSession } from "next-auth/react";
import {
  Building2,
  Users,
  Mail,
  Trash2,
  Loader2,
  Copy,
  Check,
  Crown,
  Shield,
  Eye,
  UserPlus,
  Bell,
  Send,
  AlertTriangle,
  Link2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useNotificationPreferences,
  useUpdatePreferences,
  useTestSlack,
} from "@/hooks/useNotifications";
import { rebuildSemantic } from "@/lib/api/semantic";
import { useI18n } from "@/hooks/useI18n";
import type { MessageTree } from "@/lib/i18n";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Member = {
  user_id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
};

type Invite = {
  invite_id: string;
  email: string;
  role: string;
  expires_at: string;
  created_at: string;
};

type OrgData = {
  org_id: string;
  name: string;
  slug: string;
  plan: string;
  max_members: number;
  member_count: number;
  country_code?: string;
  base_currency?: string;
  locale?: string;
  regional_packs?: string[];
};

const LOCALE_OPTIONS = ["en-US", "en-GB", "tr-TR", "de-DE"] as const;
const CURRENCY_OPTIONS = ["USD", "EUR", "GBP", "TRY", "AED", "SGD"]; // i18n-exempt: ISO 4217 currency codes are locale-invariant
const COUNTRY_OPTIONS = ["US", "GB", "TR", "DE", "AE", "SG"] as const;

// ── Role badge ────────────────────────────────────────────────────────────────

type Roles = MessageTree["settingsWorkspace"]["roles"];

function roleLabel(role: string, roles: Roles): string {
  return roles[role as keyof Roles] ?? role;
}

function RoleBadge({ role }: { role: string }) {
  const { t } = useI18n();
  const roles = t.settingsWorkspace.roles;
  const cfg: Record<string, { cls: string; icon: React.ElementType }> = {
    owner:   { cls: "bg-amber-950/30 text-amber-400 ring-amber-500/20",  icon: Crown  },
    admin:   { cls: "bg-mapblue-950/30 text-mapblue-400 ring-mapblue-500/20",     icon: Shield },
    cfo:     { cls: "bg-brass-950/30 text-brass-400 ring-brass-500/20", icon: Shield },
    analyst: { cls: "bg-muted text-muted-foreground ring-border",         icon: Users  },
    viewer:  { cls: "bg-muted text-muted-foreground ring-border",         icon: Eye    },
  };
  const c = cfg[role] ?? cfg.analyst;
  const Icon = c.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset", c.cls)}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      {roleLabel(role, roles)}
    </span>
  );
}

// ── Alert Preferences Panel ───────────────────────────────────────────────────

function AlertPreferencesPanel() {
  const { t } = useI18n();
  const ws = t.settingsWorkspace;
  const { data: prefs, isLoading } = useNotificationPreferences();
  const updatePrefs = useUpdatePreferences();
  const testSlack = useTestSlack();

  const [slackWebhook, setSlackWebhook] = useState("");
  const [slackChannel, setSlackChannel] = useState("");
  const [emailList, setEmailList] = useState("");
  const [minSeverity, setMinSeverity] = useState<"info" | "warning" | "critical">("warning");
  const [dailyDigest, setDailyDigest] = useState(false);
  const [initialized, setInitialized] = useState(false);

  // Populate form when prefs load
  if (prefs && !initialized) {
    setSlackWebhook(prefs.slack_webhook_url ?? "");
    setSlackChannel(prefs.slack_channel ?? "");
    setEmailList((prefs.email_recipients ?? []).join(", "));
    setMinSeverity(prefs.min_severity ?? "warning");
    setDailyDigest(prefs.daily_digest_enabled ?? false);
    setInitialized(true);
  }

  function handleSave(e: FormEvent) {
    e.preventDefault();
    const emailRecipients = emailList
      .split(",")
      .map((e) => e.trim())
      .filter(Boolean);

    const channels: string[] = ["dashboard"];
    if (slackWebhook) channels.push("slack");
    if (emailRecipients.length > 0) channels.push("email");

    updatePrefs.mutate({
      slack_webhook_url: slackWebhook || null,
      slack_channel:     slackChannel || null,
      email_recipients:  emailRecipients,
      min_severity:      minSeverity,
      daily_digest_enabled: dailyDigest,
      channels,
    });
  }

  function handleTestSlack() {
    testSlack.mutate();
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {ws.alerts.loading}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Bell className="h-4 w-4 text-primary" aria-hidden="true" />
        <h2 className="text-sm font-semibold">{ws.alerts.title}</h2>
      </div>

      <form onSubmit={handleSave} className="space-y-4">
        {/* Slack */}
        <div className="rounded-md border border-border bg-muted/20 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-[#4A154B]">
              <Link2 className="h-3.5 w-3.5 text-white" aria-hidden="true" />
            </div>
            <h3 className="text-sm font-medium">{ws.alerts.slack.title}</h3>
          </div>
          <p className="text-xs text-muted-foreground">
            {ws.alerts.slack.body}{" "}
            <a
              href="https://api.slack.com/messaging/webhooks"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline"
            >
              {ws.alerts.slack.howto}
            </a>
          </p>
          <div className="space-y-2">
            <div>
              <label htmlFor="slack-webhook" className="mb-1 block text-xs font-medium">
                {ws.alerts.slack.webhookLabel}
              </label>
              <input
                id="slack-webhook"
                type="url"
                value={slackWebhook}
                onChange={(e) => setSlackWebhook(e.target.value)}
                placeholder={ws.alerts.slack.webhookPlaceholder}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div>
              <label htmlFor="slack-channel" className="mb-1 block text-xs font-medium">
                {ws.alerts.slack.channelLabel}
              </label>
              <input
                id="slack-channel"
                type="text"
                value={slackChannel}
                onChange={(e) => setSlackChannel(e.target.value)}
                placeholder={ws.alerts.slack.channelPlaceholder}
                className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            {slackWebhook && (
              <button
                type="button"
                onClick={handleTestSlack}
                disabled={testSlack.isPending}
                className="flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
              >
                {testSlack.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="h-3 w-3" aria-hidden="true" />
                )}
                {ws.alerts.slack.test}
              </button>
            )}
            {testSlack.isSuccess && (
              <p className="flex items-center gap-1 text-xs text-emerald-400">
                <Check className="h-3 w-3" aria-hidden="true" />
                {ws.alerts.slack.testSent}
              </p>
            )}
            {testSlack.isError && (
              <p className="flex items-center gap-1 text-xs text-destructive">
                <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                {ws.alerts.slack.testFailed}
              </p>
            )}
          </div>
        </div>

        {/* Email */}
        <div className="space-y-2">
          <label htmlFor="email-list" className="block text-xs font-medium">
            {ws.alerts.email.label}
          </label>
          <input
            id="email-list"
            type="text"
            value={emailList}
            onChange={(e) => setEmailList(e.target.value)}
            placeholder={ws.alerts.email.placeholder}
            className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <p className="text-[10px] text-muted-foreground">{ws.alerts.email.hint}</p>
        </div>

        {/* Min severity */}
        <div className="space-y-2">
          <label className="block text-xs font-medium">{ws.alerts.severity.label}</label>
          <div className="flex gap-2">
            {(["info", "warning", "critical"] as const).map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => setMinSeverity(level)}
                className={cn(
                  "rounded-md border px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                  minSeverity === level
                    ? level === "critical"
                      ? "border-red-500/50 bg-red-500/10 text-red-400"
                      : level === "warning"
                      ? "border-amber-500/50 bg-amber-500/10 text-amber-400"
                      : "border-blue-500/50 bg-blue-500/10 text-blue-400"
                    : "border-border text-muted-foreground hover:bg-muted/30"
                )}
              >
                {ws.alerts.severity[level]}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground">
            {ws.alerts.severity.hint}
          </p>
        </div>

        {/* Daily digest */}
        <label className="flex cursor-pointer items-center gap-3">
          <div
            role="switch"
            aria-checked={dailyDigest}
            onClick={() => setDailyDigest((v) => !v)}
            className={cn(
              "relative h-5 w-9 rounded-full transition-colors",
              dailyDigest ? "bg-primary" : "bg-muted"
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                dailyDigest ? "translate-x-4" : "translate-x-0.5"
              )}
            />
          </div>
          <div>
            <p className="text-sm font-medium">{ws.alerts.digest.title}</p>
            <p className="text-[10px] text-muted-foreground">{ws.alerts.digest.body}</p>
          </div>
        </label>

        {/* Save button */}
        <div className="flex items-center gap-3 pt-1">
          <button
            type="submit"
            disabled={updatePrefs.isPending}
            className="flex items-center gap-1.5 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {updatePrefs.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
            {ws.alerts.save}
          </button>
          {updatePrefs.isSuccess && (
            <span className="flex items-center gap-1 text-xs text-emerald-400">
              <Check className="h-3 w-3" aria-hidden="true" />
              {ws.alerts.saved}
            </span>
          )}
          {updatePrefs.isError && (
            <span className="text-xs text-destructive">{ws.alerts.saveFailed}</span>
          )}
        </div>
      </form>
    </div>
  );
}

// ── Locale & regional packs ───────────────────────────────────────────────────

function LocaleSettingsPanel({
  org,
  isAdmin,
  headers,
  onUpdated,
}: {
  org: OrgData;
  isAdmin: boolean;
  headers: () => Promise<Record<string, string>>;
  onUpdated: (next: OrgData) => void;
}) {
  const { t } = useI18n();
  const ws = t.settingsWorkspace;
  const [locale, setLocale] = useState(org.locale ?? "en-US");
  const [currency, setCurrency] = useState(org.base_currency ?? "USD");
  const [country, setCountry] = useState(org.country_code ?? "US");
  const [trPack, setTrPack] = useState((org.regional_packs ?? []).includes("tr"));
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<"ok" | "err" | null>(null);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!isAdmin) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const packs = trPack ? ["tr"] : [];
      const res = await fetch(`${API_BASE}/api/v1/org/me`, {
        method: "PATCH",
        headers: await headers(),
        body: JSON.stringify({
          locale,
          base_currency: currency,
          country_code: country,
          regional_packs: packs,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? ws.locale.saveFailed);
      onUpdated({
        ...org,
        ...(data.data ?? {}),
        locale,
        base_currency: currency,
        country_code: country,
        regional_packs: packs,
        member_count: org.member_count,
      });
      setSaveMsg("ok");
    } catch {
      setSaveMsg("err");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
      <div>
        <h2 className="text-sm font-semibold">{ws.locale.title}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {ws.locale.subtitle}
        </p>
      </div>
      <form onSubmit={handleSave} className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="org-locale" className="mb-1 block text-xs font-medium">{ws.locale.localeLabel}</label>
          <select
            id="org-locale"
            value={locale}
            disabled={!isAdmin}
            onChange={(e) => setLocale(e.target.value)}
            className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          >
            {LOCALE_OPTIONS.map((o) => (
              <option key={o} value={o}>{ws.localeOptions[o]}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="org-currency" className="mb-1 block text-xs font-medium">{ws.locale.currencyLabel}</label>
          <select
            id="org-currency"
            value={currency}
            disabled={!isAdmin}
            onChange={(e) => setCurrency(e.target.value)}
            className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          >
            {CURRENCY_OPTIONS.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="org-country" className="mb-1 block text-xs font-medium">{ws.locale.countryLabel}</label>
          <select
            id="org-country"
            value={country}
            disabled={!isAdmin}
            onChange={(e) => setCountry(e.target.value)}
            className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          >
            {COUNTRY_OPTIONS.map((o) => (
              <option key={o} value={o}>{ws.countries[o]}</option>
            ))}
          </select>
        </div>
        <label className="flex cursor-pointer items-center gap-3 sm:col-span-2">
          <div
            role="switch"
            aria-checked={trPack}
            aria-disabled={!isAdmin}
            onClick={() => isAdmin && setTrPack((v) => !v)}
            className={cn(
              "relative h-5 w-9 rounded-full transition-colors",
              trPack ? "bg-primary" : "bg-muted",
              !isAdmin && "opacity-50"
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                trPack ? "translate-x-4" : "translate-x-0.5"
              )}
            />
          </div>
          <div>
            <p className="text-sm font-medium">{ws.locale.trPackTitle}</p>
            <p className="text-[10px] text-muted-foreground">
              {ws.locale.trPackBody}
            </p>
          </div>
        </label>
        {isAdmin && (
          <div className="flex items-center gap-3 sm:col-span-2">
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {ws.locale.save}
            </button>
            {saveMsg === "ok" && (
              <span className="flex items-center gap-1 text-xs text-emerald-400">
                <Check className="h-3 w-3" aria-hidden="true" />
                {ws.locale.saved}
              </span>
            )}
            {saveMsg === "err" && (
              <span className="text-xs text-destructive">{ws.locale.saveFailed}</span>
            )}
          </div>
        )}
      </form>
    </div>
  );
}

function SemanticModelPanel({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useI18n();
  const ws = t.settingsWorkspace;
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function handleRebuild() {
    setBusy(true);
    setMsg(null);
    try {
      const snap = await rebuildSemantic();
      setMsg(
        ws.semantic.rebuilt
          .replace("{count}", String(snap.metrics.length))
          .replace("{period}", snap.period.key)
      );
    } catch (err) {
      setMsg(err instanceof Error ? err.message : ws.semantic.rebuildFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-medium">{ws.semantic.title}</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        {ws.semantic.subtitle}
      </p>
      <button
        type="button"
        disabled={!isAdmin || busy}
        onClick={() => void handleRebuild()}
        className="mt-3 inline-flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        {busy && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
        {ws.semantic.rebuild}
      </button>
      {msg && <p className="mt-2 text-xs text-muted-foreground">{msg}</p>}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function WorkspaceSettingsPage() {
  const { t, locale } = useI18n();
  const ws = t.settingsWorkspace;
  const dateTag = locale === "tr" ? "tr-TR" : "en-US";
  const { data: session } = useSession();
  const accessToken = (session as { accessToken?: string } | null)?.accessToken;

  const [org, setOrg]           = useState<OrgData | null>(null);
  const [members, setMembers]   = useState<Member[]>([]);
  const [invites, setInvites]   = useState<Invite[]>([]);
  const [loading, setLoading]   = useState(false);
  const [loaded, setLoaded]     = useState(false);
  const [error, setError]       = useState<string | null>(null);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole]   = useState("analyst");
  const [inviting, setInviting]       = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  async function headers() {
    return {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    };
  }

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [orgRes, membersRes, invitesRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/org/me`,      { headers: await headers() }),
        fetch(`${API_BASE}/api/v1/org/members`, { headers: await headers() }),
        fetch(`${API_BASE}/api/v1/org/invites`, { headers: await headers() }),
      ]);

      if (orgRes.status === 400) {
        setError(ws.errors.noWorkspace);
        setLoaded(true);
        return;
      }

      const [orgData, membersData, invitesData] = await Promise.all([
        orgRes.json(),
        membersRes.json(),
        invitesRes.json(),
      ]);

      setOrg(orgData.data);
      setMembers(membersData.data?.members ?? []);
      setInvites(invitesData.data ?? []);
      setLoaded(true);
    } catch {
      setError(ws.errors.loadFailed);
    } finally {
      setLoading(false);
    }
  }

  // Load on first render
  if (!loaded && !loading && accessToken) void loadData();

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    if (!inviteEmail) return;
    setInviting(true);
    setInviteError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/org/invite`, {
        method: "POST",
        headers: await headers(),
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? ws.errors.inviteFailed);

      // Add to invites list
      setInvites((prev) => [
        {
          invite_id: data.data.invite_id,
          email:     data.data.email,
          role:      data.data.role,
          expires_at: data.data.expires_at,
          created_at: new Date().toISOString(),
        },
        ...prev,
      ]);

      // Copy invite token to clipboard
      if (data.data.token) {
        const inviteUrl = `${window.location.origin}/auth/register?invite=${data.data.token}`;
        await navigator.clipboard.writeText(inviteUrl).catch(() => {});
        setCopiedToken(data.data.invite_id);
        setTimeout(() => setCopiedToken(null), 3000);
      }

      setInviteEmail("");
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : ws.errors.generic);
    } finally {
      setInviting(false);
    }
  }

  async function cancelInvite(inviteId: string) {
    await fetch(`${API_BASE}/api/v1/org/invites/${inviteId}`, {
      method: "DELETE",
      headers: await headers(),
    });
    setInvites((prev) => prev.filter((i) => i.invite_id !== inviteId));
  }

  async function removeMember(userId: string) {
    const res = await fetch(`${API_BASE}/api/v1/org/members/${userId}`, {
      method: "DELETE",
      headers: await headers(),
    });
    if (res.ok) setMembers((prev) => prev.filter((m) => m.user_id !== userId));
  }

  const isAdmin = session?.user.role === "owner" || session?.user.role === "admin";

  return (
    <div className="space-y-6 p-5 max-w-2xl">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{ws.title}</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {ws.subtitle}
        </p>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {ws.loading}
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive">
          {error}
          {error === ws.errors.noWorkspace && (
            <div className="mt-2">
              <a href="/settings/workspace/create" className="text-primary underline">
                {ws.createWorkspace}
              </a>
            </div>
          )}
        </div>
      )}

      {/* Org info */}
      {org && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Building2 className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div className="flex-1">
              <p className="font-semibold">{org.name}</p>
              <p className="text-xs text-muted-foreground">/{org.slug}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span className="rounded bg-muted px-2 py-0.5 capitalize">{ws.planBadge.replace("{plan}", org.plan)}</span>
                <span>{ws.memberCount.replace("{count}", String(org.member_count)).replace("{max}", String(org.max_members))}</span>
                {org.locale && (
                  // i18n-exempt: backend data values (org locale tag + ISO currency code)
                  <span className="rounded bg-muted px-2 py-0.5">{org.locale} · {org.base_currency ?? "USD"}</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {org && loaded && !error && (
        <LocaleSettingsPanel
          org={org}
          isAdmin={isAdmin}
          headers={headers}
          onUpdated={setOrg}
        />
      )}

      {org && loaded && !error && <SemanticModelPanel isAdmin={isAdmin} />}

      {loaded && !error && <AlertPreferencesPanel />}

      {/* Members */}
      {loaded && !error && (
        <div className="rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <Users className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              {ws.members.title.replace("{count}", String(members.length))}
            </h2>
          </div>
          <div className="divide-y divide-border/50">
            {members.map((m) => (
              <div key={m.user_id} className="flex items-center gap-3 px-4 py-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                  {(m.full_name ?? m.email).slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm font-medium">{m.full_name ?? m.email}</p>
                  <p className="truncate text-xs text-muted-foreground">{m.email}</p>
                </div>
                <RoleBadge role={m.role} />
                {isAdmin && m.user_id !== session?.user.id && m.role !== "owner" && (
                  <button
                    onClick={() => removeMember(m.user_id)}
                    className="rounded p-1 text-muted-foreground transition-colors hover:text-destructive"
                    aria-label={ws.members.removeAria.replace("{email}", m.email)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            ))}
            {!members.length && (
              <p className="px-4 py-3 text-sm text-muted-foreground">{ws.members.empty}</p>
            )}
          </div>
        </div>
      )}

      {/* Invite */}
      {isAdmin && loaded && !error && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-medium">
            <UserPlus className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            {ws.invite.title}
          </h2>

          {inviteError && (
            <p className="mb-3 rounded border border-destructive/30 bg-destructive/8 px-3 py-2 text-xs text-destructive">
              {inviteError}
            </p>
          )}

          <form onSubmit={handleInvite} className="flex gap-2">
            <input
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder={ws.invite.placeholder}
              className={cn(
                "h-8 flex-1 rounded-md border border-border bg-background px-3 text-sm",
                "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
            />
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="analyst">{ws.roles.analyst}</option>
              <option value="viewer">{ws.roles.viewer}</option>
              <option value="admin">{ws.roles.admin}</option>
            </select>
            <button
              type="submit"
              disabled={inviting || !inviteEmail}
              className={cn(
                "flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground",
                "transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50"
              )}
            >
              {inviting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Mail className="h-3 w-3" />}
              {ws.invite.button}
            </button>
          </form>

          <p className="mt-2 text-xs text-muted-foreground">
            {ws.invite.hint}
          </p>
        </div>
      )}

      {/* Pending invites */}
      {isAdmin && invites.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">{ws.pendingInvites.title.replace("{count}", String(invites.length))}</h2>
          </div>
          <div className="divide-y divide-border/50">
            {invites.map((inv) => (
              <div key={inv.invite_id} className="flex items-center gap-3 px-4 py-3">
                <Mail className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm">{inv.email}</p>
                  <p className="text-xs text-muted-foreground">
                    {ws.pendingInvites.expiresAt
                      .replace("{role}", roleLabel(inv.role, ws.roles))
                      .replace("{date}", new Date(inv.expires_at).toLocaleDateString(dateTag))}
                  </p>
                </div>
                <button
                  onClick={async () => {
                    const url = `${window.location.origin}/auth/register?invite=${inv.invite_id}`;
                    await navigator.clipboard.writeText(url).catch(() => {});
                    setCopiedToken(inv.invite_id);
                    setTimeout(() => setCopiedToken(null), 2000);
                  }}
                  className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
                  aria-label={ws.pendingInvites.copyAria}
                >
                  {copiedToken === inv.invite_id ? (
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  onClick={() => cancelInvite(inv.invite_id)}
                  className="rounded p-1 text-muted-foreground transition-colors hover:text-destructive"
                  aria-label={ws.pendingInvites.cancelAria}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

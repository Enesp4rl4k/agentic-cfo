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
} from "lucide-react";
import { cn } from "@/lib/utils";

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
};

// ── Role badge ────────────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  const cfg: Record<string, { label: string; cls: string; icon: React.ElementType }> = {
    owner:   { label: "Owner",   cls: "bg-amber-950/30 text-amber-400 ring-amber-500/20",  icon: Crown  },
    admin:   { label: "Admin",   cls: "bg-blue-950/30 text-blue-400 ring-blue-500/20",     icon: Shield },
    cfo:     { label: "CFO",     cls: "bg-violet-950/30 text-violet-400 ring-violet-500/20", icon: Shield },
    analyst: { label: "Analyst", cls: "bg-muted text-muted-foreground ring-border",         icon: Users  },
    viewer:  { label: "Viewer",  cls: "bg-muted text-muted-foreground ring-border",         icon: Eye    },
  };
  const c = cfg[role] ?? cfg.analyst;
  const Icon = c.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset", c.cls)}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      {c.label}
    </span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function WorkspaceSettingsPage() {
  const { data: session } = useSession();
  const accessToken = (session as any)?.accessToken as string | undefined;

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
        setError("Henüz bir workspace'e üye değilsiniz.");
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
      setError("Veriler yüklenirken hata oluştu.");
    } finally {
      setLoading(false);
    }
  }

  // Load on first render
  if (!loaded && !loading && accessToken) loadData();

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
      if (!res.ok) throw new Error(data?.detail ?? "Davet gönderilemedi.");

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
      setInviteError(err instanceof Error ? err.message : "Hata oluştu.");
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
        <h1 className="text-lg font-semibold tracking-tight">Workspace Ayarları</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Organizasyonunuzu ve üyelerinizi yönetin
        </p>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Yükleniyor…
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive">
          {error}
          {error.includes("workspace") && (
            <div className="mt-2">
              <a href="/settings/workspace/create" className="text-primary underline">
                Workspace oluşturun →
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
                <span className="rounded bg-muted px-2 py-0.5 capitalize">{org.plan} plan</span>
                <span>{org.member_count} / {org.max_members} üye</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Members */}
      {loaded && !error && (
        <div className="rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <Users className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              Üyeler ({members.length})
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
                    aria-label={`${m.email} kişisini çıkar`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            ))}
            {!members.length && (
              <p className="px-4 py-3 text-sm text-muted-foreground">Henüz üye yok.</p>
            )}
          </div>
        </div>
      )}

      {/* Invite */}
      {isAdmin && loaded && !error && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-medium">
            <UserPlus className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            Üye Davet Et
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
              placeholder="kullanici@sirket.com"
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
              <option value="analyst">Analyst</option>
              <option value="viewer">Viewer</option>
              <option value="admin">Admin</option>
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
              Davet Et
            </button>
          </form>

          <p className="mt-2 text-xs text-muted-foreground">
            Davet bağlantısı otomatik olarak panonuza kopyalanır.
          </p>
        </div>
      )}

      {/* Pending invites */}
      {isAdmin && invites.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">Bekleyen Davetler ({invites.length})</h2>
          </div>
          <div className="divide-y divide-border/50">
            {invites.map((inv) => (
              <div key={inv.invite_id} className="flex items-center gap-3 px-4 py-3">
                <Mail className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm">{inv.email}</p>
                  <p className="text-xs text-muted-foreground">
                    {inv.role} · {new Date(inv.expires_at).toLocaleDateString("tr-TR")} tarihine kadar
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
                  aria-label="Bağlantıyı kopyala"
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
                  aria-label="Daveti iptal et"
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

"use client";

import { useState } from "react";
import { Bell, Trash2, CheckCheck, Settings, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useNotifications,
  useMarkRead,
  useMarkAllRead,
  useDeleteNotification,
  useNotificationPreferences,
  useUpdatePreferences,
  useTestSlack,
  type Notification,
  type NotificationPreferences,
} from "@/hooks/useNotifications";

// ── Helpers ────────────────────────────────────────────────────────────────────

function levelBadge(level: Notification["level"]) {
  const base = "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide";
  switch (level) {
    case "critical": return <span className={cn(base, "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300")}>Kritik</span>;
    case "error":    return <span className={cn(base, "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300")}>Hata</span>;
    case "warning":  return <span className={cn(base, "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300")}>Uyarı</span>;
    default:         return <span className={cn(base, "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300")}>Bilgi</span>;
  }
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1)  return "az önce";
  if (mins < 60) return `${mins} dakika önce`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs} saat önce`;
  return `${Math.floor(hrs / 24)} gün önce`;
}

// ── Notification row ───────────────────────────────────────────────────────────

function NotifRow({
  n,
  onRead,
  onDelete,
}: {
  n: Notification;
  onRead: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div
      className={cn(
        "group flex items-start gap-3 rounded-lg border border-border p-4 transition-colors",
        n.is_read ? "bg-card opacity-70" : "bg-card shadow-sm"
      )}
    >
      {/* Unread dot */}
      <div className="mt-1 shrink-0">
        {n.is_read ? (
          <span className="block h-2 w-2 rounded-full bg-muted" />
        ) : (
          <span className="block h-2 w-2 rounded-full bg-red-500" />
        )}
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          {levelBadge(n.level)}
          {n.domain && (
            <span className="text-[10px] text-muted-foreground capitalize font-medium">
              {n.domain}
            </span>
          )}
          {n.source && (
            <span className="text-[10px] text-muted-foreground">· {n.source}</span>
          )}
        </div>
        <p className={cn("text-sm leading-snug", !n.is_read && "font-medium text-foreground")}>
          {n.message}
        </p>
        <div className="mt-1.5 flex items-center gap-3 text-xs text-muted-foreground">
          <span>{relativeTime(n.created_at)}</span>
          {n.priority_score > 0 && (
            <span>Öncelik: {n.priority_score.toFixed(1)}</span>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        {!n.is_read && (
          <button
            aria-label="Okundu işaretle"
            onClick={() => onRead(n.id)}
            title="Okundu işaretle"
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <CheckCheck className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          aria-label="Sil"
          onClick={() => onDelete(n.id)}
          title="Sil"
          className="rounded p-1 text-muted-foreground hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/30"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Preferences panel ──────────────────────────────────────────────────────────

function PreferencesPanel({ prefs }: { prefs: NotificationPreferences }) {
  const update   = useUpdatePreferences();
  const testSlack = useTestSlack();

  const [slackUrl, setSlackUrl] = useState(prefs.slack_webhook_url ?? "");
  const [emails, setEmails]     = useState((prefs.email_recipients ?? []).join(", "));
  const [channels, setChannels] = useState<string[]>(prefs.channels ?? ["dashboard"]);
  const [minSev, setMinSev]     = useState(prefs.min_severity ?? "warning");
  const [saved, setSaved]       = useState(false);

  function toggleChannel(ch: string) {
    setChannels((prev) =>
      prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch]
    );
  }

  async function handleSave() {
    await update.mutateAsync({
      channels,
      min_severity: minSev as NotificationPreferences["min_severity"],
      slack_webhook_url: slackUrl || null,
      email_recipients: emails
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="space-y-5 rounded-lg border border-border bg-card p-5">
      <h3 className="text-sm font-semibold">Bildirim Tercihleri</h3>

      {/* Channels */}
      <div>
        <label className="mb-2 block text-xs font-medium text-muted-foreground">
          Kanallar
        </label>
        <div className="flex flex-wrap gap-2">
          {["dashboard", "email", "slack"].map((ch) => (
            <button
              key={ch}
              onClick={() => toggleChannel(ch)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                channels.includes(ch)
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-primary/50"
              )}
            >
              {ch === "dashboard" ? "Dashboard" : ch === "email" ? "E-posta" : "Slack"}
            </button>
          ))}
        </div>
      </div>

      {/* Min severity */}
      <div>
        <label className="mb-2 block text-xs font-medium text-muted-foreground">
          Minimum önem seviyesi
        </label>
        <select
          value={minSev}
          onChange={(e) => setMinSev(e.target.value as "critical" | "warning" | "info")}
          className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value="info">Bilgi (tümü)</option>
          <option value="warning">Uyarı ve üzeri</option>
          <option value="critical">Yalnızca kritik</option>
        </select>
      </div>

      {/* Slack webhook */}
      {channels.includes("slack") && (
        <div>
          <label className="mb-2 block text-xs font-medium text-muted-foreground">
            Slack Webhook URL
          </label>
          <div className="flex gap-2">
            <input
              type="url"
              value={slackUrl}
              onChange={(e) => setSlackUrl(e.target.value)}
              placeholder="https://hooks.slack.com/services/..."
              className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <button
              onClick={() => testSlack.mutate()}
              disabled={!slackUrl || testSlack.isPending}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
            >
              {testSlack.isPending ? "Gönderiliyor…" : "Test Et"}
            </button>
          </div>
          {testSlack.isSuccess && (
            <p className="mt-1 text-xs text-green-600">✓ Test mesajı gönderildi</p>
          )}
          {testSlack.isError && (
            <p className="mt-1 text-xs text-red-600">Slack testi başarısız</p>
          )}
        </div>
      )}

      {/* Email recipients */}
      {channels.includes("email") && (
        <div>
          <label className="mb-2 block text-xs font-medium text-muted-foreground">
            E-posta alıcıları (virgülle ayırın)
          </label>
          <input
            type="text"
            value={emails}
            onChange={(e) => setEmails(e.target.value)}
            placeholder="cfo@sirket.com, ceo@sirket.com"
            className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
      )}

      <button
        onClick={handleSave}
        disabled={update.isPending}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {update.isPending ? "Kaydediliyor…" : saved ? "✓ Kaydedildi" : "Kaydet"}
      </button>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function NotificationsPage() {
  const [tab, setTab]           = useState<"all" | "unread" | "settings">("all");
  const [levelFilter, setLevel] = useState<string>("all");

  const { data, isLoading } = useNotifications(tab === "unread");
  const { data: prefs }     = useNotificationPreferences();
  const markRead   = useMarkRead();
  const markAllRead = useMarkAllRead();
  const deleteNotif = useDeleteNotification();

  const notifications = (data?.notifications ?? []).filter(
    (n) => levelFilter === "all" || n.level === levelFilter
  );
  const unreadCount = data?.unread_count ?? 0;

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-semibold">Bildirimler</h1>
          {unreadCount > 0 && (
            <span className="rounded-full bg-red-500 px-2 py-0.5 text-xs font-bold text-white">
              {unreadCount}
            </span>
          )}
        </div>
        {unreadCount > 0 && tab !== "settings" && (
          <button
            onClick={() => markAllRead.mutate()}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <CheckCheck className="h-3.5 w-3.5" />
            Tümünü okundu işaretle
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg border border-border bg-muted/30 p-1">
        {(
          [
            { id: "all",      label: "Tümü" },
            { id: "unread",   label: `Okunmamış${unreadCount > 0 ? ` (${unreadCount})` : ""}` },
            { id: "settings", label: "Ayarlar", icon: <Settings className="h-3 w-3" /> },
          ] as const
        ).map(({ id, label, ...rest }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              tab === id
                ? "bg-background shadow-sm text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {"icon" in rest ? rest.icon : null}
            {label}
          </button>
        ))}
      </div>

      {/* Settings tab */}
      {tab === "settings" && prefs && <PreferencesPanel prefs={prefs} />}

      {/* Notification list */}
      {tab !== "settings" && (
        <>
          {/* Level filter */}
          <div className="flex flex-wrap gap-1.5">
            {["all", "critical", "error", "warning", "info"].map((lvl) => (
              <button
                key={lvl}
                onClick={() => setLevel(lvl)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
                  levelFilter === lvl
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/40"
                )}
              >
                {lvl === "all"
                  ? "Tümü"
                  : lvl === "critical"
                  ? "Kritik"
                  : lvl === "error"
                  ? "Hata"
                  : lvl === "warning"
                  ? "Uyarı"
                  : "Bilgi"}
              </button>
            ))}
          </div>

          {/* List */}
          {isLoading ? (
            <div className="space-y-2">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
              ))}
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
              <Bell className="h-10 w-10 opacity-20" />
              <p className="text-sm">
                {tab === "unread" ? "Okunmamış bildirim yok" : "Bildirim bulunamadı"}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {notifications.map((n) => (
                <NotifRow
                  key={n.id}
                  n={n}
                  onRead={(id) => markRead.mutate(id)}
                  onDelete={(id) => deleteNotif.mutate(id)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}

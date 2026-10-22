"use client";

import { useState } from "react";
import { Bell, Trash2, CheckCheck, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";
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

function levelBadge(level: Notification["level"], labels: Record<string, string>) {
  const base = "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide";
  switch (level) {
    case "critical": return <span className={cn(base, "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300")}>{labels.critical}</span>;
    case "error":    return <span className={cn(base, "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300")}>{labels.error}</span>;
    case "warning":  return <span className={cn(base, "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300")}>{labels.warning}</span>;
    default:         return <span className={cn(base, "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300")}>{labels.info}</span>;
  }
}

function relativeTime(iso: string, ago: Record<string, string>): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1)  return ago.justNow;
  if (mins < 60) return ago.mins.replace("{count}", String(mins));
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return ago.hours.replace("{count}", String(hrs));
  return ago.days.replace("{count}", String(Math.floor(hrs / 24)));
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
  const { t } = useI18n();
  const notif = t.notifications;

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
          {levelBadge(n.level, notif.levels)}
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
          <span>{relativeTime(n.created_at, notif.ago)}</span>
          {n.priority_score > 0 && (
            <span>{notif.priority.replace("{score}", n.priority_score.toFixed(1))}</span>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        {!n.is_read && (
          <button
            aria-label={notif.markRead}
            onClick={() => onRead(n.id)}
            title={notif.markRead}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <CheckCheck className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          aria-label={notif.delete}
          onClick={() => onDelete(n.id)}
          title={notif.delete}
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
  const { t } = useI18n();
  const p = t.notifications.prefs;

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
      <h3 className="text-sm font-semibold">{p.heading}</h3>

      {/* Channels */}
      <div>
        <label className="mb-2 block text-xs font-medium text-muted-foreground">
          {p.channels}
        </label>
        <div className="flex flex-wrap gap-2">
          {[
            { key: "dashboard", label: p.channelDashboard },
            { key: "email", label: p.channelEmail },
            { key: "slack", label: p.channelSlack },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => toggleChannel(key)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                channels.includes(key)
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-primary/50"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Min severity */}
      <div>
        <label className="mb-2 block text-xs font-medium text-muted-foreground">
          {p.minSeverity}
        </label>
        <select
          value={minSev}
          onChange={(e) => setMinSev(e.target.value as "critical" | "warning" | "info")}
          className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value="info">{p.sevInfo}</option>
          <option value="warning">{p.sevWarning}</option>
          <option value="critical">{p.sevCritical}</option>
        </select>
      </div>

      {/* Slack webhook */}
      {channels.includes("slack") && (
        <div>
          <label className="mb-2 block text-xs font-medium text-muted-foreground">
            {p.slackUrl}
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
              {testSlack.isPending ? p.slackSending : p.slackTest}
            </button>
          </div>
          {testSlack.isSuccess && (
            <p className="mt-1 text-xs text-green-600">{p.slackSuccess}</p>
          )}
          {testSlack.isError && (
            <p className="mt-1 text-xs text-red-600">{p.slackError}</p>
          )}
        </div>
      )}

      {/* Email recipients */}
      {channels.includes("email") && (
        <div>
          <label className="mb-2 block text-xs font-medium text-muted-foreground">
            {p.emailRecipients}
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
        {update.isPending ? p.saving : saved ? p.saved : p.save}
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
  const { t } = useI18n();
  const notif = t.notifications;

  const notifications = (data?.notifications ?? []).filter(
    (n) => levelFilter === "all" || n.level === levelFilter
  );
  const unreadCount = data?.unread_count ?? 0;

  const levelLabels: Record<string, string> = {
    all: notif.filters.all,
    critical: notif.levels.critical,
    error: notif.levels.error,
    warning: notif.levels.warning,
    info: notif.levels.info,
  };

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-semibold">{notif.title}</h1>
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
            {notif.markAllRead}
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg border border-border bg-muted/30 p-1">
        {(
          [
            { id: "all",      label: notif.tabs.all },
            { id: "unread",   label: unreadCount > 0 ? `${notif.tabs.unread} (${unreadCount})` : notif.tabs.unread },
            { id: "settings", label: notif.tabs.settings, icon: <Settings className="h-3 w-3" /> },
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
                {levelLabels[lvl] ?? lvl}
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
                {tab === "unread" ? notif.emptyUnread : notif.empty}
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

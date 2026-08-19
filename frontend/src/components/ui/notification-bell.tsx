"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { Bell } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useNotifications,
  useMarkRead,
  useMarkAllRead,
  type Notification,
} from "@/hooks/useNotifications";

// ── Level helpers ──────────────────────────────────────────────────────────────

function levelDot(level: Notification["level"]) {
  const base = "mt-0.5 h-2 w-2 shrink-0 rounded-full";
  switch (level) {
    case "critical": return <span className={cn(base, "bg-red-500")} />;
    case "error":    return <span className={cn(base, "bg-orange-500")} />;
    case "warning":  return <span className={cn(base, "bg-yellow-400")} />;
    default:         return <span className={cn(base, "bg-blue-400")} />;
  }
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1)  return "şimdi";
  if (mins < 60) return `${mins}dk önce`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}sa önce`;
  return `${Math.floor(hrs / 24)}g önce`;
}

// ── Dropdown item ──────────────────────────────────────────────────────────────

function NotifItem({
  n,
  onRead,
}: {
  n: Notification;
  onRead: (id: string) => void;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 px-3 py-2.5 text-xs transition-colors hover:bg-muted/50",
        !n.is_read && "bg-muted/20"
      )}
      role="listitem"
    >
      {levelDot(n.level)}
      <div className="min-w-0 flex-1">
        <p className={cn("leading-snug text-foreground", !n.is_read && "font-medium")}>
          {n.message}
        </p>
        <p className="mt-0.5 text-muted-foreground">
          {n.domain && <span className="capitalize">{n.domain} · </span>}
          {relativeTime(n.created_at)}
        </p>
      </div>
      {!n.is_read && (
        <button
          aria-label="Okundu olarak işaretle"
          onClick={() => onRead(n.id)}
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          ✕
        </button>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const { data } = useNotifications(false);
  const markRead   = useMarkRead();
  const markAllRead = useMarkAllRead();

  const notifications = data?.notifications ?? [];
  const unreadCount   = data?.unread_count ?? 0;

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      {/* Bell button */}
      <button
        aria-label={`Bildirimler${unreadCount > 0 ? ` — ${unreadCount} okunmamış` : ""}`}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span
            aria-hidden="true"
            className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white"
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="dialog"
          aria-label="Bildirim paneli"
          className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-card shadow-xl"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-sm font-semibold">
              Bildirimler
              {unreadCount > 0 && (
                <span className="ml-1.5 rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  {unreadCount}
                </span>
              )}
            </span>
            {unreadCount > 0 && (
              <button
                onClick={() => markAllRead.mutate()}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Tümünü okundu işaretle
              </button>
            )}
          </div>

          {/* List */}
          <div
            role="list"
            className="max-h-[360px] overflow-y-auto divide-y divide-border"
          >
            {notifications.length === 0 ? (
              <p className="py-8 text-center text-xs text-muted-foreground">
                Bildirim yok
              </p>
            ) : (
              notifications.slice(0, 10).map((n) => (
                <NotifItem
                  key={n.id}
                  n={n}
                  onRead={(id) => markRead.mutate(id)}
                />
              ))
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-border px-3 py-2 text-center">
            <Link
              href="/notifications"
              onClick={() => setOpen(false)}
              className="text-xs text-primary hover:underline"
            >
              Tüm bildirimleri gör
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

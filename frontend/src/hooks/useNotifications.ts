"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface Notification {
  id: string;
  level: "info" | "warning" | "error" | "critical";
  domain: string;
  message: string;
  source: string | null;
  job_id: string | null;
  action: string | null;
  priority_score: number;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface NotificationPreferences {
  org_id: string;
  channels: string[];
  min_severity: "info" | "warning" | "critical";
  slack_webhook_url: string | null;
  slack_channel: string | null;
  email_recipients: string[];
  daily_digest_enabled: boolean;
  digest_hour_utc: number;
  quiet_hours_start: number | null;
  quiet_hours_end: number | null;
  escalation_only: boolean;
  updated_at: string | null;
}

export interface NotificationsResponse {
  notifications: Notification[];
  unread_count: number;
  total: number;
}

// ── API helpers ────────────────────────────────────────────────────────────────

async function fetchNotifications(unreadOnly = false): Promise<NotificationsResponse> {
  const res = await apiClient.get("/notifications", {
    params: { unread_only: unreadOnly, limit: 50 },
  });
  return res.data.data;
}

async function fetchPreferences(): Promise<NotificationPreferences> {
  const res = await apiClient.get("/notifications/preferences");
  return res.data.data;
}

async function markOneRead(id: string): Promise<void> {
  await apiClient.patch(`/notifications/${id}/read`);
}

async function markAllReadApi(): Promise<void> {
  await apiClient.patch("/notifications/read-all");
}

async function deleteNotificationApi(id: string): Promise<void> {
  await apiClient.delete(`/notifications/${id}`);
}

async function updatePreferencesApi(
  prefs: Partial<NotificationPreferences>
): Promise<NotificationPreferences> {
  const res = await apiClient.put("/notifications/preferences", prefs);
  return res.data.data;
}

async function testSlackApi(): Promise<{ sent: boolean }> {
  const res = await apiClient.post("/notifications/test-slack");
  return res.data.data;
}

// ── Hooks ──────────────────────────────────────────────────────────────────────

/** Poll every 30s — drives the bell badge count */
export function useNotifications(unreadOnly = false) {
  return useQuery<NotificationsResponse>({
    queryKey: ["notifications", { unreadOnly }],
    queryFn: () => fetchNotifications(unreadOnly),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

/** Lightweight unread count — polls every 20s */
export function useUnreadCount(): number {
  const { data } = useQuery<NotificationsResponse>({
    queryKey: ["notifications", { unreadOnly: false }],
    queryFn: () => fetchNotifications(false),
    refetchInterval: 20_000,
    staleTime: 10_000,
  });
  return data?.unread_count ?? 0;
}

export function useNotificationPreferences() {
  return useQuery<NotificationPreferences>({
    queryKey: ["notification-preferences"],
    queryFn: fetchPreferences,
    staleTime: 5 * 60_000,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: markOneRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: markAllReadApi,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useDeleteNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteNotificationApi,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: updatePreferencesApi,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-preferences"] });
    },
  });
}

export function useTestSlack() {
  return useMutation({ mutationFn: testSlackApi });
}

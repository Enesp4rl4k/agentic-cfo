import { apiClient } from "@/lib/api/client";

// What happened to the company's Slack and webhook destinations (backend app/api/notifications.py,
// services/delivery_status.py). Owner and admin only. Never a URL or a response body: the destination is its host.

export interface DeliveryFailure {
  /** A stable reason code ("timeout", "http_503", "failed" for anything unknown). */
  code: string;
  tr?: string;
  en?: string;
}

export interface DeliveryDestination {
  channel: "slack" | "webhook" | string;
  /** The destination's host name. */
  destination: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_failure: DeliveryFailure | null;
  /** The latest attempt failed. */
  failing: boolean;
}

type Envelope<T> = { data: T; error: string | null };

export async function getDeliveryStatus(): Promise<DeliveryDestination[]> {
  const res = await apiClient.get<Envelope<{ destinations: DeliveryDestination[] }>>("/notifications/delivery-status");
  return res.data.data.destinations;
}

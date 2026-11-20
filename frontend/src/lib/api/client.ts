import axios from "axios";
import { getSession, signOut } from "next-auth/react";
import { REFRESH_FAILED } from "@/lib/authRefresh";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: `${API_URL}/api/v1`,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// ── Request: attach NextAuth access_token ─────────────────────────────────────
function sessionExpired(): never {
  void signOut({ redirect: false })
    .catch(() => null)
    .finally(() => {
      window.location.href = "/auth/login?reason=session_expired";
    });
  throw new Error("Session expired. Please log in again.");
}

apiClient.interceptors.request.use(async (config) => {
  const session = await getSession().catch(() => null); // can fail in SSR
  // The refresh token could not be traded for a new access token: sending the
  // old one would only earn a 401.
  if (session?.error === REFRESH_FAILED && typeof window !== "undefined") sessionExpired();
  const token = session?.accessToken;
  if (token) {
    config.headers = config.headers ?? {};
    config.headers["Authorization"] = `Bearer ${token}`;
  }
  return config;
});

// ── Response: unwrap envelope + handle 401 ────────────────────────────────────
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status;

    // Session expired or invalid token — sign out and redirect to login
    if (status === 401 && typeof window !== "undefined") {
      try {
        await signOut({ redirect: false });
        window.location.href = "/auth/login?reason=session_expired";
      } catch {
        // signOut failed — still redirect
        window.location.href = "/auth/login?reason=session_expired";
      }
      return Promise.reject(new Error("Session expired. Please log in again."));
    }

    const message =
      error.response?.data?.detail ??
      error.response?.data?.error ??
      error.message ??
      "Unknown error";
    // Still an Error, but it keeps the status: a caller that must tell "not
    // allowed" (403, with a reason worth showing) from "could not reach the
    // server" can.
    return Promise.reject(Object.assign(new Error(message), { status }));
  }
);

// ── streamUrl — an authenticated URL for EventSource ─────────────────────────
/**
 * EventSource cannot send an Authorization header, which is why the progress
 * stream used to take no user at all. The backend now wants a short-lived
 * ticket scoped to one job; ask for one right before each connect (tickets
 * expire, and a reconnect should not reuse a stale one).
 */
export async function streamUrl(jobId: string): Promise<string> {
  const res = await apiClient.post<{ data: { ticket: string } }>(
    `/stream/${jobId}/ticket`,
  );
  const ticket = encodeURIComponent(res.data.data.ticket);
  return `${API_URL}/api/v1/stream/${jobId}?ticket=${ticket}`;
}

// ── fetchWithAuth — for native fetch() calls (e.g. file downloads) ────────────
/**
 * Drop-in replacement for window.fetch() that attaches the current
 * NextAuth access token as a Bearer header.
 *
 * Use this instead of raw fetch() whenever calling authenticated endpoints,
 * e.g. PDF export, SSE streams, or any endpoint not going through apiClient.
 */
export async function fetchWithAuth(
  input: RequestInfo | URL,
  init: RequestInit = {}
): Promise<Response> {
  const session = await getSession().catch(() => null);
  const token = session?.accessToken;

  const headers = new Headers(init.headers as HeadersInit | undefined);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(input, { ...init, headers });

  // Mirror the 401 handling from the axios interceptor
  if (res.status === 401 && typeof window !== "undefined") {
    await signOut({ redirect: false }).catch(() => null);
    window.location.href = "/auth/login?reason=session_expired";
  }

  return res;
}

import axios from "axios";
import { getSession, signOut } from "next-auth/react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: `${API_URL}/api/v1`,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// ── Request: attach NextAuth access_token ─────────────────────────────────────
apiClient.interceptors.request.use(async (config) => {
  try {
    const session = await getSession();
    const token = (session as any)?.accessToken as string | undefined;
    if (token) {
      config.headers = config.headers ?? {};
      config.headers["Authorization"] = `Bearer ${token}`;
    }
  } catch {
    // getSession can fail in SSR — silently skip
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
    return Promise.reject(new Error(message));
  }
);

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
  const token = (session as any)?.accessToken as string | undefined;

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

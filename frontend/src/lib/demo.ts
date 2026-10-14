import { signIn } from "next-auth/react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * One-click guest demo entry (DEMO_PLAN D1).
 *
 * Mints an isolated demo session on the backend (POST /demo/guest) and signs
 * it in through the existing NextAuth credentials shortcut — the `access_token`
 * branch of authorize() validates it against /auth/me. No signup, no password.
 *
 * Returns true when the session is established; false on any failure
 * (demo_mode off, backend down) so callers can show an honest error state.
 */
export async function startGuestDemo(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/demo/guest`, {
      method: "POST",
    });
    if (!res.ok) return false;

    const json = await res.json().catch(() => null);
    const token: unknown = json?.data?.access_token;
    if (typeof token !== "string" || !token) return false;

    const result = await signIn("credentials", {
      access_token: token,
      refresh_token: json?.data?.refresh_token ?? "",
      redirect: false,
    });
    return !result?.error;
  } catch {
    return false;
  }
}

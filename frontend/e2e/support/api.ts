import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

export const API = "http://localhost:8000/api/v1";
/** The same API with a model behind it (the stub), used by the boardroom step only. */
export const API_WITH_MODEL = "http://localhost:8001/api/v1";
export const PASSWORD = "Pilot-2026-pass";

type Login = { token: string; userId: string; role: string; orgId: string | null };

export async function register(request: APIRequestContext, email: string, fullName: string) {
  const res = await request.post(`${API}/auth/register`, { data: { email, password: PASSWORD, full_name: fullName } });
  expect(res.status(), await res.text()).toBe(201);
}

/**
 * The API allows five sign-ins per minute per address (brute-force protection), and a registration
 * through the screen uses three of them. The journey signs in as four people, so it paces itself:
 * never more than four in any minute, and a person who already signed in in the browser is not
 * signed in again.
 */
const signIns: number[] = [];
const WINDOW_MS = 61_000;
export function noteSignIns(count: number) {
  for (let i = 0; i < count; i++) signIns.push(Date.now());
}
async function signInSlot() {
  for (;;) {
    const now = Date.now();
    while (signIns.length && now - signIns[0] > WINDOW_MS) signIns.shift();
    if (signIns.length < 4) break;
    await new Promise((resolve) => setTimeout(resolve, WINDOW_MS - (now - signIns[0]) + 250));
  }
  signIns.push(Date.now());
}

export async function login(request: APIRequestContext, email: string): Promise<Login> {
  await signInSlot();
  const res = await request.post(`${API}/auth/login`, { data: { email, password: PASSWORD } });
  expect(res.status(), await res.text()).toBe(200);
  const { data } = await res.json();
  return { token: data.access_token, userId: data.user.user_id, role: data.user.role, orgId: data.user.org_id };
}

export const bearer = (token: string) => ({ Authorization: `Bearer ${token}` });

/** The owner invites someone by e-mail through the product's own endpoint. */
export async function invite(request: APIRequestContext, ownerToken: string, email: string, role: string) {
  const res = await request.post(`${API}/org/invite`, { headers: bearer(ownerToken), data: { email, role } });
  expect(res.status(), await res.text()).toBe(201);
}

/** The invited person accepts with the token from the invitation e-mail. */
export async function acceptInvite(request: APIRequestContext, inviteToken: string, fullName: string) {
  const res = await request.post(`${API}/org/invite/accept`, {
    data: { token: inviteToken, full_name: fullName, password: PASSWORD },
  });
  return res;
}

/** People who have accepted the current privacy notice in the browser: the app stays closed to them until they do. */
const acceptedNotice = new Set<string>();

/**
 * The prompt every new person meets after signing in. The journey accepts it explicitly, once per person, the way a
 * person does (the button is the only way through); it does not depend on the clock or on anything else.
 */
export async function acceptNoticePrompt(page: Page, email: string) {
  const prompt = page.getByRole("dialog", { name: "Devam etmeden önce lütfen okuyun" });
  await expect(prompt).toBeVisible({ timeout: 60_000 });
  await prompt.getByRole("button", { name: "Okudum, kabul ediyorum" }).click();
  await expect(prompt).toBeHidden({ timeout: 30_000 });
  acceptedNotice.add(email);
}

const sessions = new Map<string, Awaited<ReturnType<BrowserContext["cookies"]>>>();

/** Sign in through the login screen, the way a person does; later visits reuse that session. */
export async function loginInBrowser(page: Page, email: string) {
  const known = sessions.get(email);
  if (known) {
    await page.context().addCookies(known);
    return;
  }
  await signInSlot();
  await page.goto("/auth/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith("/auth"), { timeout: 60_000 });
  if (!acceptedNotice.has(email)) await acceptNoticePrompt(page, email);
  sessions.set(email, await page.context().cookies());
}

const FRONTEND = path.resolve(__dirname, "..", "..");

/** Run one of support/probe.py's read-only commands and return its JSON. */
export function probe<T>(...args: string[]): T {
  const out = execFileSync(process.env.E2E_PYTHON ?? "python", [path.join("e2e", "support", "probe.py"), ...args], {
    cwd: FRONTEND,
    encoding: "utf-8",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    timeout: 120_000,
  });
  return JSON.parse(out.trim().split("\n").pop() as string) as T;
}

export type OutboxRow = {
  recipient: string;
  status: string;
  subject: string;
  body: string;
  source: string;
  source_ref: string;
  last_error: string | null;
};

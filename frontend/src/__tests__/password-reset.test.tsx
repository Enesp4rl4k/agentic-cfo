/**
 * The password-reset pages: `/auth/forgot-password` and `/auth/reset-password`.
 *
 * The API is mocked with the shapes backend/tests/test_password_reset.py pins: forgot-password answers
 * the same for every address; reset-password answers `{data: {state}}` with 400 for invalid / expired /
 * used. Checked: the same confirmation whatever the address, the token read from the fragment and
 * removed from the address bar, sent in a POST body only, every state of the reset page, and the
 * headers that keep the token out of a Referer.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o", name: "Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true, baseCurrency: "TRY", locale: "tr-TR",
  }),
}));
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);

import ForgotPasswordPage from "@/app/auth/forgot-password/page";
import ResetPasswordPage from "@/app/auth/reset-password/page";

const fetchMock = vi.fn();
const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
const calls = (needle: string) => fetchMock.mock.calls.filter(([url]) => String(url).includes(needle));

beforeEach(() => {
  vi.clearAllMocks();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/");
});

describe("forgot password", () => {
  it("posts the address in the body and shows one confirmation", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { data: { accepted: true }, error: null }));
    const user = userEvent.setup();
    render(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("E-posta"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: "Sıfırlama bağlantısı gönder" }));

    expect(await screen.findByText("E-postanızı kontrol edin")).toBeInTheDocument();
    const [url, init] = calls("/auth/forgot-password")[0];
    expect(init.method).toBe("POST");
    expect(String(url)).not.toContain("ada");
    expect(JSON.parse(init.body)).toEqual({ email: "ada@example.com" });
  });

  it("says the same words for any address: it never mentions whether an account exists", async () => {
    fetchMock.mockResolvedValue(json(200, { data: { accepted: true }, error: null }));
    const user = userEvent.setup();
    render(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("E-posta"), "nobody@example.com");
    await user.click(screen.getByRole("button", { name: "Sıfırlama bağlantısı gönder" }));
    const body = await screen.findByText(/Bu adresteki hesap sıfırlanabiliyorsa/);
    expect(body.textContent).not.toMatch(/bulunamadı|kayıtlı değil|hesap yok/i);
  });

  it("tells a person who is rate-limited to wait, and keeps the form", async () => {
    fetchMock.mockResolvedValueOnce(json(429, { error: "limit" }));
    const user = userEvent.setup();
    render(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("E-posta"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: "Sıfırlama bağlantısı gönder" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Çok fazla deneme");
    expect(screen.getByLabelText("E-posta")).toBeInTheDocument();
  });

  it("links back to sign in", () => {
    render(<ForgotPasswordPage />);
    expect(screen.getByRole("link", { name: "Girişe dön" })).toHaveAttribute("href", "/auth/login");
  });
});

describe("reset password", () => {
  async function fill(user: ReturnType<typeof userEvent.setup>, first: string, second = first) {
    await user.type(screen.getByLabelText("Yeni şifre"), first);
    await user.type(screen.getByLabelText("Yeni şifreyi tekrarlayın"), second);
  }

  it("reads the token from the fragment, takes it out of the address bar, and posts it in the body", async () => {
    window.history.replaceState(null, "", "/auth/reset-password#token=" + "a".repeat(64));
    fetchMock.mockResolvedValueOnce(json(200, { data: { state: "ok" }, error: null }));
    const user = userEvent.setup();
    render(<ResetPasswordPage />);

    await screen.findByLabelText("Yeni şifre");
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("a".repeat(16));
    await fill(user, "BrandNewPassword456!");
    await user.click(screen.getByRole("button", { name: "Yeni şifreyi kaydet" }));

    expect(await screen.findByText("Şifreniz değişti")).toBeInTheDocument();
    const [url, init] = calls("/auth/reset-password")[0];
    expect(String(url)).not.toContain("a".repeat(16));
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ token: "a".repeat(64), new_password: "BrandNewPassword456!" });
    expect(screen.getByRole("link", { name: "Giriş yap" })).toHaveAttribute("href", "/auth/login");
    expect(window.location.href).not.toContain("BrandNewPassword");
  });

  it("also accepts a hand-copied ?token= and removes it just the same", async () => {
    window.history.replaceState(null, "", "/auth/reset-password?token=" + "b".repeat(64));
    render(<ResetPasswordPage />);
    await screen.findByLabelText("Yeni şifre");
    expect(window.location.search).toBe("");
  });

  it("without a token it is an invalid link and does not ask the server", async () => {
    render(<ResetPasswordPage />);
    expect(await screen.findByText("Bu sıfırlama bağlantısı geçersiz")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Yeni bağlantı iste" })).toHaveAttribute("href", "/auth/forgot-password");
  });

  it.each([
    ["invalid", "Bu sıfırlama bağlantısı geçersiz"],
    ["expired", "Bu sıfırlama bağlantısının süresi dolmuş"],
    ["used", "Bu sıfırlama bağlantısı zaten kullanılmış"],
  ])("names the state %s the server reports, and offers a new link", async (state, title) => {
    window.history.replaceState(null, "", "/auth/reset-password#token=" + "c".repeat(64));
    fetchMock.mockResolvedValueOnce(json(400, { data: { state }, error: "x" }));
    const user = userEvent.setup();
    render(<ResetPasswordPage />);
    await screen.findByLabelText("Yeni şifre");
    await fill(user, "BrandNewPassword456!");
    await user.click(screen.getByRole("button", { name: "Yeni şifreyi kaydet" }));
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.queryByLabelText("Yeni şifre")).toBeNull();
    expect(screen.getByRole("link", { name: "Yeni bağlantı iste" })).toBeInTheDocument();
  });

  it("will not submit passwords that differ or are too short", async () => {
    window.history.replaceState(null, "", "/auth/reset-password#token=" + "d".repeat(64));
    const user = userEvent.setup();
    render(<ResetPasswordPage />);
    await screen.findByLabelText("Yeni şifre");
    expect(screen.getByRole("button", { name: "Yeni şifreyi kaydet" })).toBeDisabled();
    await fill(user, "BrandNewPassword456!", "Different789Password!");
    await user.click(screen.getByRole("button", { name: "Yeni şifreyi kaydet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("İki şifre aynı değil");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the form for a failure that is not about the token (rate limit, outage)", async () => {
    window.history.replaceState(null, "", "/auth/reset-password#token=" + "e".repeat(64));
    fetchMock.mockResolvedValueOnce(json(429, { error: "limit" })).mockRejectedValueOnce(new Error("offline"));
    const user = userEvent.setup();
    render(<ResetPasswordPage />);
    await screen.findByLabelText("Yeni şifre");
    await fill(user, "BrandNewPassword456!");
    await user.click(screen.getByRole("button", { name: "Yeni şifreyi kaydet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Çok fazla deneme");
    await user.click(screen.getByRole("button", { name: "Yeni şifreyi kaydet" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Şifre değiştirilemedi"));
    expect(screen.getByLabelText("Yeni şifre")).toBeInTheDocument();
  });
});

describe("the token stays out of a Referer", () => {
  it("the reset path is served with Referrer-Policy: no-referrer, after the general rule", async () => {
    const config = (await import(/* @vite-ignore */ resolve(process.cwd(), "next.config.mjs"))).default;
    const rules = await config.headers();
    const matching = rules.filter((r: { source: string }) => r.source === "/(.*)" || r.source.startsWith("/auth/:page("));
    const policy = matching
      .flatMap((r: { headers: { key: string; value: string }[] }) => r.headers)
      .filter((h: { key: string }) => h.key === "Referrer-Policy")
      .map((h: { value: string }) => h.value);
    expect(policy.at(-1)).toBe("no-referrer");
  });

  it("the page's layout declares the same", () => {
    const layout = readFileSync(resolve(process.cwd(), "src/app/auth/reset-password/layout.tsx"), "utf8");
    expect(layout).toContain('referrer: "no-referrer"');
  });
});

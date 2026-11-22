/**
 * E-mail verification pages: `/auth/verify-email` (the link, and the resend form), the login page's answer
 * to an unverified account, and the register page's "check your e-mail" step.
 *
 * The API is mocked with the shapes backend/tests/test_email_verification.py pins.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { signIn } from "next-auth/react";

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o", name: "Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true, baseCurrency: "TRY", locale: "tr-TR",
  }),
}));
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);
vi.mock("@/components/demo/GuestDemoButton", () => ({ GuestDemoButton: () => null }));

import VerifyEmailPage from "@/app/auth/verify-email/page";
import LoginPage from "@/app/auth/login/page";
import RegisterPage from "@/app/auth/register/page";

const fetchMock = vi.fn();
const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
const calls = (needle: string) => fetchMock.mock.calls.filter(([url]) => String(url).includes(needle));

beforeEach(() => {
  vi.clearAllMocks();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/");
});

describe("the verification link", () => {
  it("verifies on load, posts the token in the body and takes it out of the address bar", async () => {
    window.history.replaceState(null, "", "/auth/verify-email#token=" + "a".repeat(64));
    fetchMock.mockResolvedValueOnce(json(200, { data: { state: "ok" }, error: null }));
    render(<VerifyEmailPage />);
    expect(await screen.findByText("Adresiniz doğrulandı")).toBeInTheDocument();
    const [url, init] = calls("/auth/verify-email")[0];
    expect(String(url)).not.toContain("a".repeat(16));
    expect(JSON.parse(init.body)).toEqual({ token: "a".repeat(64) });
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("link", { name: "Giriş yap" })).toHaveAttribute("href", "/auth/login");
  });

  it.each([
    ["invalid", "Bu doğrulama bağlantısı geçersiz"],
    ["expired", "Bu doğrulama bağlantısının süresi dolmuş"],
    ["used", "Bu doğrulama bağlantısı zaten kullanılmış"],
  ])("names the state %s", async (state, title) => {
    window.history.replaceState(null, "", "/auth/verify-email#token=" + "b".repeat(64));
    fetchMock.mockResolvedValueOnce(json(400, { data: { state }, error: "x" }));
    render(<VerifyEmailPage />);
    expect(await screen.findByText(title)).toBeInTheDocument();
    // an invalid or expired link offers a new one; a used one points to signing in
    if (state === "used") expect(screen.queryByLabelText("E-posta")).toBeNull();
    else expect(screen.getByLabelText("E-posta")).toBeInTheDocument();
  });

  it("without a token it is the resend form, and the confirmation is the same for any address", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { data: { accepted: true }, error: null }));
    const user = userEvent.setup();
    render(<VerifyEmailPage />);
    await user.type(await screen.findByLabelText("E-posta"), "nobody@example.com");
    await user.click(screen.getByRole("button", { name: "Bağlantıyı yeniden gönder" }));
    const note = await screen.findByText(/doğrulanmayı bekleyen bir hesap varsa/);
    expect(note.textContent).not.toMatch(/bulunamadı|kayıtlı değil|hesap yok/i);
    expect(JSON.parse(calls("/auth/resend-verification")[0][1].body)).toEqual({ email: "nobody@example.com" });
  });

  it("tells a rate-limited person to wait", async () => {
    fetchMock.mockResolvedValueOnce(json(429, { error: "limit" }));
    const user = userEvent.setup();
    render(<VerifyEmailPage />);
    await user.type(await screen.findByLabelText("E-posta"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: "Bağlantıyı yeniden gönder" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Çok fazla deneme");
  });
});

describe("signing in with an unverified address", () => {
  it("says so and offers the link again, instead of 'wrong password'", async () => {
    vi.mocked(signIn).mockResolvedValue({ error: "email_unverified" } as never);
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText("E-posta"), "ada@example.com");
    await user.type(screen.getByLabelText("Şifre"), "StrongPassword123!");
    await user.click(screen.getByRole("button", { name: "Giriş Yap" }));
    expect(await screen.findByText(/henüz doğrulanmadı/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Doğrulama bağlantısını yeniden gönder" })).toHaveAttribute("href", "/auth/verify-email");
    expect(screen.queryByText(/E-posta veya şifre hatalı/)).toBeNull();
  });
});

describe("registering", () => {
  it("does not sign in or create the workspace when the address must be verified first", async () => {
    fetchMock.mockResolvedValueOnce(json(201, { data: { accepted: true, verification_required: true }, error: null }));
    const user = userEvent.setup();
    render(<RegisterPage />);
    const field = (id: string) => document.getElementById(id) as HTMLInputElement;
    await user.type(field("fullName"), "Ada Lovelace");
    await user.type(field("email"), "ada@example.com");
    await user.type(field("password"), "StrongPassword123!");
    await user.click(screen.getByRole("button", { name: /Devam Et/ }));
    await user.type(await waitFor(() => field("orgName")), "Acme");
    await user.click(screen.getByRole("button", { name: "Workspace Oluştur" }));

    expect(await screen.findByText("E-postanızı kontrol edin")).toBeInTheDocument();
    await waitFor(() => expect(signIn).not.toHaveBeenCalled());
    expect(calls("/org/create")).toHaveLength(0);
    expect(screen.getByRole("link", { name: /yeniden gönderin/ })).toHaveAttribute("href", "/auth/verify-email");
  });
});

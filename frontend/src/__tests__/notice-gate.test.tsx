import { readFileSync } from "node:fs";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NoticeGate } from "@/components/privacy/NoticeGate";
import { tr } from "@/lib/i18n/messages/tr";

const { client, auth } = vi.hoisted(() => ({
  client: { get: vi.fn(), post: vi.fn() },
  auth: { status: "authenticated" as string, signOut: vi.fn() },
}));
vi.mock("@/lib/api/client", () => ({ apiClient: client }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ status: auth.status }), signOut: auth.signOut }));
vi.mock("@/hooks/useI18n", () => ({ useI18n: () => ({ locale: "tr", t: tr }) }));
vi.mock("@/components/ui/logo", () => ({ Logo: () => null }));

const doc = (version: string, must: boolean, url: string | null = "https://example.test/metin") => ({
  version, url, accepted_version: must ? null : version, accepted_at: must ? null : "2026-11-01T10:00:00Z", must_accept: must,
});
const state = (privacy: boolean, terms: boolean) => ({
  privacy_notice: doc("taslak-1", privacy), terms: doc("taslak-1", terms), must_accept: privacy || terms,
});
const serve = (data: ReturnType<typeof state>) => client.get.mockResolvedValue({ data: { data } });
const APP = "uygulama ekrani";
const mount = () => render(<NoticeGate><p>{APP}</p></NoticeGate>);

beforeEach(() => {
  auth.status = "authenticated";
});
afterEach(() => vi.clearAllMocks());

describe("NoticeGate", () => {
  it("shows the prompt, not the app, while the server says a current version is pending", async () => {
    serve(state(true, true));
    mount();
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.queryByText(APP)).toBeNull();
    expect(screen.getByText(tr.settingsPrivacy.notices.privacyNotice)).toBeTruthy();
    expect(screen.getByText(tr.settingsPrivacy.notices.terms)).toBeTruthy();
    expect(screen.getAllByText("Sürüm taslak-1")).toHaveLength(2);
    const links = screen.getAllByRole("link", { name: tr.noticeGate.open });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["https://example.test/metin", "https://example.test/metin"]);
  });

  it("renders the app when nothing is pending, and never asks", async () => {
    serve(state(false, false));
    mount();
    expect(await screen.findByText(APP)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(client.post).not.toHaveBeenCalled();
  });

  it("does not render the app while the state is still being read", () => {
    client.get.mockReturnValue(new Promise(() => undefined));
    mount();
    expect(screen.queryByText(APP)).toBeNull();
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("has no pre-ticked box, no close button, and accepts nothing until the explicit button is pressed", async () => {
    serve(state(true, false));
    mount();
    await screen.findByRole("dialog");
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /kapat|close|×/i })).toBeNull();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(client.post).not.toHaveBeenCalled();
    expect(screen.queryByText(APP)).toBeNull();
  });

  it("accepts exactly the pending versions it showed, then opens the app", async () => {
    serve(state(true, false));
    client.post.mockResolvedValue({ data: { data: { recorded: ["privacy_notice"], notices: state(false, false) } } });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: tr.noticeGate.accept }));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith("/privacy/notices/accept", { privacy_notice: "taslak-1" }));
    expect(await screen.findByText(APP)).toBeTruthy();
  });

  it("does not open the app when the acceptance could not be saved", async () => {
    serve(state(true, true));
    client.post.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: tr.noticeGate.accept }));
    expect(await screen.findByText(tr.noticeGate.acceptFailed)).toBeTruthy();
    expect(screen.queryByText(APP)).toBeNull();
  });

  it("when the server refuses a stale version it shows the new one and records nothing for it", async () => {
    serve(state(true, false));
    client.post.mockRejectedValue(Object.assign(new Error("stale version: ['privacy_notice']"), { status: 409 }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: tr.noticeGate.accept }));
    expect(await screen.findByText(tr.noticeGate.stale)).toBeTruthy();
    expect(client.get).toHaveBeenCalledTimes(2); // read again: the prompt now shows what the server publishes
    expect(screen.queryByText(APP)).toBeNull();
  });

  it("keeps sign-out reachable in the prompt", async () => {
    serve(state(true, true));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: tr.noticeGate.signOut }));
    expect(auth.signOut).toHaveBeenCalledWith({ callbackUrl: "/auth/login" });
  });

  it("says plainly when a text has no link yet, and still offers sign-out", async () => {
    client.get.mockResolvedValue({ data: { data: { ...state(true, false), privacy_notice: doc("taslak-1", true, null) } } });
    mount();
    expect(await screen.findByText(tr.noticeGate.noLink)).toBeTruthy();
    expect(screen.getByRole("button", { name: tr.noticeGate.signOut })).toBeTruthy();
  });

  it("renders the link only for an http(s) URL, never javascript: or a relative value", async () => {
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "/aydinlatma", "TBD"]) {
      client.get.mockResolvedValue({ data: { data: { ...state(true, false), privacy_notice: doc("taslak-1", true, bad) } } });
      const { unmount } = mount();
      expect(await screen.findByText(tr.noticeGate.noLink)).toBeTruthy();
      expect(screen.queryByRole("link")).toBeNull();
      unmount();
    }
    client.get.mockResolvedValue({ data: { data: { ...state(true, false), privacy_notice: doc("taslak-1", true, "https://example.test/metin") } } });
    mount();
    expect(await screen.findByRole("link", { name: tr.noticeGate.open })).toBeTruthy();
  });

  it("fails closed when the state cannot be read: retry and sign-out, no app", async () => {
    client.get.mockRejectedValueOnce(new Error("net"));
    mount();
    expect(await screen.findByText(tr.noticeGate.loadFailed)).toBeTruthy();
    expect(screen.queryByText(APP)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: tr.noticeGate.signOut }));
    expect(auth.signOut).toHaveBeenCalled();
    client.get.mockResolvedValue({ data: { data: state(false, false) } });
    fireEvent.click(screen.getByRole("button", { name: tr.noticeGate.retry }));
    expect(await screen.findByText(APP)).toBeTruthy();
  });

  it("leaves a signed-out visitor to the sign-in redirect and asks nothing", () => {
    auth.status = "unauthenticated";
    mount();
    expect(screen.getByText(APP)).toBeTruthy();
    expect(client.get).not.toHaveBeenCalled();
  });

  it("is what wraps the signed-in app shell", () => {
    const layout = readFileSync("src/app/(dashboard)/layout.tsx", "utf-8");
    expect(layout).toMatch(/<NoticeGate>\s*<DashboardShell>/);
  });
});

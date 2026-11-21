/**
 * The page the invitation e-mail links to (`/auth/accept-invite?token=…`).
 *
 * It used to be a 404, so an invited person could not join. The API is mocked with the shapes
 * backend/tests/test_invite_accept.py pins. Checked: the states the person can be in (unknown, expired,
 * used), who may accept how (new account, existing account with its password, a session of the invited
 * address, a session of somebody else), and that accepting lands them in the company they were invited
 * to, also when they already have one of their own.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { signIn, signOut, useSession } from "next-auth/react";

const query = { token: "tok123" as string | null };
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (k: string) => (k === "token" ? query.token : null) }),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/auth/accept-invite",
}));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o", name: "Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true, baseCurrency: "TRY", locale: "tr-TR",
  }),
}));
const clearWorkspace = vi.fn();
vi.mock("@/store/companyContext", () => ({ useCompanyContextStore: () => ({ clearWorkspace }) }));
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);

import AcceptInvitePage from "@/app/auth/accept-invite/page";

const fetchMock = vi.fn();
const assign = vi.fn();
const update = vi.fn().mockResolvedValue(null);

const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
const preview = (over: Record<string, unknown> = {}) =>
  json(200, { data: { state: "valid", email: "musavir@example.com", role: "smmm", org_name: "Deniz Tekstil A.Ş.", account_exists: false, ...over }, error: null });
const accepted = (over: Record<string, unknown> = {}) =>
  json(201, { data: { access_token: "new-token", joined_org_id: "client", user: { org_id: "client" }, ...over }, error: null });

function session(user: Record<string, unknown> | null) {
  vi.mocked(useSession).mockReturnValue(
    (user
      ? { data: { user, accessToken: "tok" }, status: "authenticated", update }
      : { data: null, status: "unauthenticated", update }) as unknown as ReturnType<typeof useSession>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("location", { ...window.location, assign });
  query.token = "tok123";
  session(null);
});

const calls = (needle: string) => fetchMock.mock.calls.filter(([url]) => String(url).includes(needle));

describe("the states of an invitation", () => {
  it.each([
    ["unknown", /Bu davet bulunamadı/],
    ["expired", /Davetin süresi dolmuş/],
    ["used", /Bu davet zaten kullanılmış/],
  ])("says plainly that it is %s, and offers no form", async (state, title) => {
    fetchMock.mockResolvedValueOnce(state === "unknown" ? json(200, { data: { state }, error: null }) : preview({ state }));
    render(<AcceptInvitePage />);
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.queryByLabelText("Şifre")).toBeNull();
    expect(screen.queryByRole("button", { name: /katıl/i })).toBeNull();
  });

  it("an invitation that was already used points to signing in", async () => {
    fetchMock.mockResolvedValueOnce(preview({ state: "used" }));
    render(<AcceptInvitePage />);
    expect(await screen.findByRole("link", { name: "Giriş yap" })).toHaveAttribute("href", "/auth/login");
  });

  it("a link without a token is an unknown invitation, without asking the server", async () => {
    query.token = null;
    render(<AcceptInvitePage />);
    expect(await screen.findByText(/Bu davet bulunamadı/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says so when the invitation cannot be read at all", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    render(<AcceptInvitePage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Davet okunamadı");
  });
});

describe("accepting", () => {
  it("names the company, the role and the address, and creates the account of someone who has none", async () => {
    fetchMock.mockResolvedValueOnce(preview()).mockResolvedValueOnce(accepted());
    vi.mocked(signIn).mockResolvedValue({ error: null } as never);
    const user = userEvent.setup();
    render(<AcceptInvitePage />);

    expect(await screen.findByText("Deniz Tekstil A.Ş. şirketine Mali müşavir olarak davet edildiniz.")).toBeInTheDocument();
    expect(screen.getByText("Davet musavir@example.com adresi içindir.")).toBeInTheDocument();
    const join = screen.getByRole("button", { name: "Hesap oluştur ve katıl" });
    expect(join).toBeDisabled(); // a password of eight characters first
    await user.type(screen.getByLabelText("Ad soyad"), "Murat Müşavir");
    await user.type(screen.getByLabelText("Şifre"), "Pilot-2026-pass");
    await user.click(join);

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/command-center"));
    const [, init] = calls("/org/invite/accept")[0];
    expect(JSON.parse(init.body)).toEqual({ token: "tok123", password: "Pilot-2026-pass", full_name: "Murat Müşavir" });
    expect(init.headers.Authorization).toBeUndefined();
    expect(signIn).toHaveBeenCalledWith("credentials", { email: "musavir@example.com", password: "Pilot-2026-pass", redirect: false });
    expect(calls("/org/switch")).toHaveLength(0); // the first company: already where they land
    expect(clearWorkspace).toHaveBeenCalled();
  });

  it("an accountant with companies of their own proves the account with its password and is taken into the new one", async () => {
    fetchMock
      .mockResolvedValueOnce(preview({ account_exists: true }))
      .mockResolvedValueOnce(accepted({ user: { org_id: "home" } })) // still acting in their own company
      .mockResolvedValueOnce(json(200, { data: { org_id: "client" }, error: null }));
    vi.mocked(signIn).mockResolvedValue({ error: null } as never);
    const user = userEvent.setup();
    render(<AcceptInvitePage />);

    await screen.findByText(/Bu adreste bir hesabınız var/);
    expect(screen.queryByLabelText("Ad soyad")).toBeNull();
    await user.type(screen.getByLabelText("Şifre"), "Pilot-2026-pass");
    await user.click(screen.getByRole("button", { name: "Şirkete katıl" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/command-center"));
    const [, sw] = calls("/org/switch")[0];
    expect(JSON.parse(sw.body)).toEqual({ org_id: "client" });
    expect(sw.headers.Authorization).toBe("Bearer new-token");
    // The cookie is made after the switch, so it carries the role of the company they land in.
    expect(fetchMock.mock.invocationCallOrder.at(-1)).toBeLessThan(vi.mocked(signIn).mock.invocationCallOrder[0]);
  });

  it("a wrong password is said as such and nothing else happens", async () => {
    fetchMock.mockResolvedValueOnce(preview({ account_exists: true })).mockResolvedValueOnce(json(401, { data: null, error: "Şifre yanlış." }));
    const user = userEvent.setup();
    render(<AcceptInvitePage />);
    await user.type(await screen.findByLabelText("Şifre"), "yanlis-sifre");
    await user.click(screen.getByRole("button", { name: "Şirkete katıl" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Şifre yanlış. Bu davet için bu adresin hesabıyla giriş yapmalısınız.");
    expect(signIn).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows the server's own sentence when it refuses for another reason", async () => {
    fetchMock.mockResolvedValueOnce(preview({ account_exists: true })).mockResolvedValueOnce(json(400, { data: null, error: "Bu davet daha önce kullanılmış." }));
    const user = userEvent.setup();
    render(<AcceptInvitePage />);
    await user.type(await screen.findByLabelText("Şifre"), "Pilot-2026-pass");
    await user.click(screen.getByRole("button", { name: "Şirkete katıl" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Bu davet daha önce kullanılmış.");
  });

  it("someone already signed in as the invited address confirms with one click, no password", async () => {
    session({ id: "u", email: "Musavir@example.com", role: "owner", orgId: "home" });
    fetchMock.mockResolvedValueOnce(preview({ account_exists: true })).mockResolvedValueOnce(accepted({ user: { org_id: "home" } })).mockResolvedValueOnce(json(200, { data: {}, error: null }));
    const user = userEvent.setup();
    render(<AcceptInvitePage />);
    await screen.findByText(/musavir@example.com ile giriş yaptınız/);
    expect(screen.queryByLabelText("Şifre")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Şirkete katıl" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/command-center"));
    const [, init] = calls("/org/invite/accept")[0];
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(JSON.parse(init.body)).toEqual({ token: "tok123" });
    expect(update).toHaveBeenCalled(); // the cookie's role is re-read
    expect(signIn).not.toHaveBeenCalled();
  });

  it("signed in as somebody else: says whose invitation it is and offers to sign out", async () => {
    session({ id: "u", email: "baska@example.com", role: "owner", orgId: "home" });
    fetchMock.mockResolvedValueOnce(preview({ account_exists: true }));
    const user = userEvent.setup();
    render(<AcceptInvitePage />);
    expect(await screen.findByText("Bu davet başka bir hesap için")).toBeInTheDocument();
    expect(screen.getByText(/baska@example.com ile giriş yaptınız; davet musavir@example.com adresi içindir/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Şirkete katıl/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Çıkış yap ve devam et" }));
    expect(signOut).toHaveBeenCalledWith({ redirect: false });
  });
});

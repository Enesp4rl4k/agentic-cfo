/**
 * The workspace screen's invite form offers exactly the roles the inviter may grant.
 *
 * It used to offer analyst and viewer (and admin to an owner), although the API accepts cfo and smmm
 * too and the accountant flow depends on it. The list comes from `invitableRoles` (lib/roles.ts,
 * checked against the backend by roles.test.ts); each role has a one-line description of its powers.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSession } from "next-auth/react";

vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("@/hooks/useNotifications", () => ({
  useNotificationPreferences: () => ({ data: undefined, isLoading: false }),
  useUpdatePreferences: () => ({ mutate: vi.fn(), isPending: false }),
  useTestSlack: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/org/SizeProfileCard", () => ({ SizeProfileCard: () => null }));
vi.mock("@/components/org/MaterialityCard", () => ({ MaterialityCard: () => null }));
vi.mock("@/components/org/BriefingRecipientsCard", () => ({ BriefingRecipientsCard: () => null }));
vi.mock("@/lib/api/semantic", () => ({ rebuildSemantic: vi.fn() }));

import WorkspaceSettingsPage from "@/app/(dashboard)/settings/workspace/page";

const fetchMock = vi.fn();
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => ({ data, error: null }) });

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith("/org/me")) return ok({ id: "o", name: "Deniz Tekstil", slug: "deniz", plan: "free", member_count: 1, max_members: 5, locale: "tr-TR", base_currency: "TRY", country_code: "TR", regional_packs: ["tr"] });
    if (String(url).endsWith("/org/members")) return ok({ members: [] });
    if (String(url).endsWith("/org/invites")) return ok([]);
    if (String(url).endsWith("/org/invite") && init?.method === "POST") {
      return { ok: true, status: 201, json: async () => ({ data: { invite_id: "i1", email: "m@x.com", role: "smmm", expires_at: "2026-12-01T00:00:00Z", email_sent: true }, error: null }) };
    }
    return ok({});
  });
});

const as = (role: string) =>
  vi.mocked(useSession).mockReturnValue({
    data: { user: { id: "u", email: "o@x.com", role, orgId: "o" }, accessToken: "tok" },
    status: "authenticated",
  } as unknown as ReturnType<typeof useSession>);

async function inviteSelect() {
  const form = (await screen.findByPlaceholderText("kullanici@sirket.com")).closest("form") as HTMLElement;
  return { form, select: within(form).getByRole("combobox") as HTMLSelectElement };
}
const offered = (select: HTMLSelectElement) => [...select.options].map((o) => o.value);

describe("the invite form", () => {
  it("offers an owner every role, the accountant and the CFO among them", async () => {
    as("owner");
    render(<WorkspaceSettingsPage />);
    const { select } = await inviteSelect();
    expect(offered(select).sort()).toEqual(["admin", "analyst", "cfo", "owner", "smmm", "viewer"]);
  });

  it("offers an admin what is below admin: no owner, no admin", async () => {
    as("admin");
    render(<WorkspaceSettingsPage />);
    const { select } = await inviteSelect();
    expect(offered(select).sort()).toEqual(["analyst", "cfo", "smmm", "viewer"]);
  });

  it("describes each offered role's powers in a line", async () => {
    as("admin");
    render(<WorkspaceSettingsPage />);
    await inviteSelect();
    expect(screen.getByText(/Şirketin mali müşaviri: kayıtları onaylar/)).toBeInTheDocument();
    expect(screen.getByText("Yalnızca görüntüler; hiçbir şeyi değiştirmez.")).toBeInTheDocument();
    expect(screen.queryByText(/Her şeyi yönetir/)).toBeNull(); // the owner's line is not offered to an admin
  });

  it("invites an accountant: the request carries role smmm, and the page says it was e-mailed", async () => {
    as("owner");
    const user = userEvent.setup();
    render(<WorkspaceSettingsPage />);
    const { form, select } = await inviteSelect();
    await user.type(within(form).getByPlaceholderText("kullanici@sirket.com"), "m@x.com");
    await user.selectOptions(select, "smmm");
    await user.click(within(form).getByRole("button"));
    const post = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/org/invite") && init?.method === "POST");
    expect(JSON.parse((post as [string, RequestInit])[1].body as string)).toEqual({ email: "m@x.com", role: "smmm" });
    expect(await screen.findByText("Davet m@x.com adresine gönderildi.")).toBeInTheDocument();
  });
});

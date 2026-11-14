/**
 * Şirket değiştirici — the accountant's way into a client's organisation.
 *
 * The API is mocked with the shapes backend/tests/test_org_membership.py pins.
 * What is checked is this component's side: it stays out of the way of a
 * single-company user, lists every organisation with the active one marked,
 * and a switch clears the workspace and reloads rather than patching state.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const getMemberships = vi.fn();
const switchOrg = vi.fn();
vi.mock("@/lib/api/orgs", () => ({
  getMemberships: () => getMemberships(),
  switchOrg: (id: string) => switchOrg(id),
}));

// useI18n resolves the org locale; pin a Turkish org so the copy asserted is Turkish.
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "home", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true,
    baseCurrency: "TRY", locale: "tr-TR",
  }),
}));

vi.mock("next-auth/react", () => ({
  useSession: () => ({ status: "authenticated", data: { user: { email: "m@x.com" } } }),
}));

const clearWorkspace = vi.fn();
vi.mock("@/store/companyContext", () => ({
  useCompanyContextStore: () => ({ clearWorkspace }),
}));

import { OrgSwitcher } from "@/components/ui/org-switcher";

const assign = vi.fn();

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <OrgSwitcher />
    </QueryClientProvider>,
  );
}

const two = {
  active_org_id: "home",
  memberships: [
    { org_id: "kaya", name: "Kaya Gıda", role: "smmm", active: false },
    { org_id: "home", name: "Mali Müşavirlik", role: "owner", active: true },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window, "location", {
    value: { assign },
    writable: true,
    configurable: true,
  });
});

describe("OrgSwitcher", () => {
  it("renders nothing for someone who belongs to one organisation", async () => {
    getMemberships.mockResolvedValue({
      active_org_id: "home",
      memberships: [{ org_id: "home", name: "Tek Şirket", role: "owner", active: true }],
    });
    const { container } = mount();
    await waitFor(() => expect(getMemberships).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it("lists every organisation with its role and marks the active one", async () => {
    getMemberships.mockResolvedValue(two);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Şirket değiştir" }));

    const items = screen.getAllByRole("menuitemradio");
    expect(items).toHaveLength(2);
    expect(screen.getByRole("menuitemradio", { name: /Kaya Gıda/ })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("menuitemradio", { name: /Mali Müşavirlik/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("Mali müşavir")).toBeInTheDocument();
    expect(screen.getByText("Sahip")).toBeInTheDocument();
  });

  it("switches, clears the workspace and reloads instead of patching state", async () => {
    getMemberships.mockResolvedValue(two);
    switchOrg.mockResolvedValue({ org_id: "kaya", name: "Kaya Gıda", role: "smmm" });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Şirket değiştir" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /Kaya Gıda/ }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/command-center"));
    expect(switchOrg).toHaveBeenCalledWith("kaya");
    expect(clearWorkspace).toHaveBeenCalledTimes(1);
  });

  it("choosing the organisation you are already in does nothing", async () => {
    getMemberships.mockResolvedValue(two);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Şirket değiştir" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /Mali Müşavirlik/ }));

    expect(switchOrg).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows the error and stays put when the switch is refused", async () => {
    getMemberships.mockResolvedValue(two);
    switchOrg.mockRejectedValue(new Error("Organizasyon bulunamadı."));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Şirket değiştir" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /Kaya Gıda/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Organizasyon bulunamadı.");
    expect(assign).not.toHaveBeenCalled();
    expect(clearWorkspace).not.toHaveBeenCalled();
  });
});

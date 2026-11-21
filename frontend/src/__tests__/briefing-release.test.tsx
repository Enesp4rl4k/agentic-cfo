/**
 * Müşavirin bülten e-postasını serbest bırakması (ADR 0008, K10).
 *
 * The delivery API is mocked with the shape briefing_delivery.deliveries returns. This checks the
 * card's side of the contract: a held e-mail is shown as held, only the accountant gets the action,
 * it asks before it posts, and what the server answers (released, already released, 403) is what shows.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/briefing", async () => (await import("./dashboard-mocks")).briefingDeliveryModule);
vi.mock("@/lib/api/orgs", async () => (await import("./dashboard-mocks")).orgsModule);
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { BriefingRelease } from "@/components/bulten/BriefingRelease";
import type { MondayBriefing } from "@/lib/api/briefing";
import { briefingDeliverySpies, membershipSpies, membershipsFor, renderWithQuery } from "./dashboard-mocks";

const { getBriefingDeliveries, releaseMondayBriefing } = briefingDeliverySpies;

const briefing = { briefing_id: "brief_org1_202505", week_start: "2025-02-01", week_end: "2025-02-07" } as MondayBriefing;
const row = (status: string) => ({
  recipient: "patron@example.com", status, reason: status === "held" ? "awaiting_accountant_release" : null,
  attempts: 0, sent_at: status === "sent" ? "2025-02-03T08:00:00" : null,
});
const show = () => renderWithQuery(<BriefingRelease briefing={briefing} />);

beforeEach(() => {
  getBriefingDeliveries.mockReset();
  releaseMondayBriefing.mockReset();
  membershipSpies.getMemberships.mockReset();
  membershipSpies.getMemberships.mockResolvedValue(membershipsFor("smmm"));
});

describe("bülten e-postasını serbest bırakma", () => {
  it("shows the held state with the week to the accountant", async () => {
    getBriefingDeliveries.mockResolvedValue([row("held")]);
    show();
    expect(await screen.findByText(/senin onayını bekliyor/)).toBeTruthy();
    expect(screen.getByText(/2025-02-01 – 2025-02-07/)).toBeTruthy();
    expect(getBriefingDeliveries).toHaveBeenCalledWith("brief_org1_202505");
  });

  it("posts the briefing id only after the confirmation, then shows the sent state", async () => {
    getBriefingDeliveries.mockResolvedValueOnce([row("held")]).mockResolvedValue([row("sent")]);
    releaseMondayBriefing.mockResolvedValue({ released: 1 });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "E-postayı serbest bırak" }));
    expect(releaseMondayBriefing).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Evet, gönder" }));
    await waitFor(() => expect(releaseMondayBriefing).toHaveBeenCalledTimes(1));
    expect(releaseMondayBriefing).toHaveBeenCalledWith("brief_org1_202505");
    expect(await screen.findByText("E-posta gönderildi.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "E-postayı serbest bırak" })).toBeNull();
  });

  it("does not post when the accountant backs out", async () => {
    getBriefingDeliveries.mockResolvedValue([row("held")]);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "E-postayı serbest bırak" }));
    fireEvent.click(await screen.findByRole("button", { name: "Vazgeç" }));
    expect(releaseMondayBriefing).not.toHaveBeenCalled();
  });

  it("shows the state the server holds when the e-mail was already released", async () => {
    getBriefingDeliveries.mockResolvedValueOnce([row("held")]).mockResolvedValue([row("sent")]);
    releaseMondayBriefing.mockResolvedValue({ released: 0 });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "E-postayı serbest bırak" }));
    fireEvent.click(await screen.findByRole("button", { name: "Evet, gönder" }));
    expect(await screen.findByText("E-posta gönderildi.")).toBeTruthy();
    expect(screen.getByText(/zaten serbest bırakılmıştı/)).toBeTruthy();
  });

  it("explains the role when the server answers 403", async () => {
    getBriefingDeliveries.mockResolvedValue([row("held")]);
    releaseMondayBriefing.mockRejectedValue(Object.assign(new Error("Bu şirketin mali müşaviri değilsiniz."), { status: 403 }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "E-postayı serbest bırak" }));
    fireEvent.click(await screen.findByRole("button", { name: "Evet, gönder" }));
    expect(await screen.findByText(/yalnız şirketin mali müşaviri/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "E-postayı serbest bırak" })).toBeTruthy();
  });

  it("gives the owner a read-only waiting state and no button", async () => {
    membershipSpies.getMemberships.mockResolvedValue(membershipsFor("owner"));
    getBriefingDeliveries.mockResolvedValue([row("held")]);
    show();
    expect(await screen.findByText(/mali müşavirinin onayını bekliyor/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows nothing for a briefing that has no e-mail", async () => {
    getBriefingDeliveries.mockResolvedValue([]);
    const { container } = show();
    await waitFor(() => expect(getBriefingDeliveries).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});

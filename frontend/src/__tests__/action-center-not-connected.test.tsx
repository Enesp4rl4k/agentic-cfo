/**
 * An approved action with no connector answers 501: the screen says nothing was done
 * and keeps the action; it never shows a success.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "./dashboard-mocks";

const { api } = vi.hoisted(() => ({
  api: { getPendingActions: vi.fn(), approveAction: vi.fn(), rejectAction: vi.fn() },
}));
vi.mock("@/lib/api/actions", () => api);
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
  }),
}));

import { getMessages } from "@/lib/i18n";
import { ActionCenter } from "@/components/ActionCenter";

const action = {
  id: "a1",
  debate_id: "d1",
  description: "Vergi ödemesi için EFT taslağı hazırla",
  responsible_agent: "cfo",
  status: "pending",
  created_at: "2026-11-21T00:00:00Z",
};

afterEach(() => vi.clearAllMocks());

describe("ActionCenter approve", () => {
  it("says the action is not connected and keeps it listed", async () => {
    api.getPendingActions.mockResolvedValue([action]);
    api.approveAction.mockRejectedValue(
      Object.assign(new Error("Bu işlem henüz bağlı değil — hiçbir şey yapılmadı."), { status: 501 }),
    );
    renderWithQuery(<ActionCenter />);
    fireEvent.click(await screen.findByText("Onayla"));
    expect(await screen.findByRole("status")).toHaveTextContent(getMessages("tr").onay.actionNotConnected);
    await waitFor(() => expect(screen.getByText(action.description)).toBeTruthy());
  });
});

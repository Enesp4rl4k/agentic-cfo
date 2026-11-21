/**
 * Kapalı dönemler — the accountant closes a month for the company they are working in.
 *
 * The API is mocked with the shapes backend/tests/test_period_lock.py pins. Checked:
 * closed months are listed and not offered again, no future month is offered, closing
 * asks first and then reloads, a refusal the server explains is shown as given, and
 * any other failure uses our wording.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "./dashboard-mocks";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true, baseCurrency: "TRY", locale: "tr-TR",
  }),
}));

import { DonemKilitleri } from "@/components/smmm/DonemKilitleri";

const NOW = new Date(2026, 2, 15); // 15 March 2026
const serve = (donemler: string[]) =>
  get.mockResolvedValue({
    data: { data: { donemler: donemler.map((d) => ({ donem: d, kilitleyen_user_id: "u" })) } },
  });

async function chooseAndClose(value: string) {
  fireEvent.change(screen.getByLabelText("Dönemi kapat"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Kapat" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("DonemKilitleri", () => {
  it("lists closed months and offers neither them nor a future month", async () => {
    serve(["2026-01"]);
    renderWithQuery(<DonemKilitleri now={NOW} />);
    expect(await screen.findByText("Kapalı: 2026-01")).toBeInTheDocument();
    const options = Array.from(screen.getByLabelText("Dönemi kapat").querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toContain("2026-03");
    expect(options).toContain("2026-02");
    expect(options).not.toContain("2026-01");
    expect(options).not.toContain("2026-04");
  });

  it("asks first, closes, and reloads", async () => {
    serve([]);
    post.mockResolvedValue({ data: {} });
    renderWithQuery(<DonemKilitleri now={NOW} />);
    await screen.findByText("Henüz kapatılmış bir dönem yok.");
    await chooseAndClose("2026-02");
    await waitFor(() => expect(post).toHaveBeenCalledWith("/smmm/donem-kilitleri", { donem: "2026-02" }));
    expect(window.confirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(get.mock.calls.filter(([url]) => String(url).includes("donem-kilitleri"))).toHaveLength(2));
  });

  it("does nothing when the person declines", async () => {
    serve([]);
    (window.confirm as ReturnType<typeof vi.fn>).mockReturnValue(false);
    renderWithQuery(<DonemKilitleri now={NOW} />);
    await screen.findByText("Henüz kapatılmış bir dönem yok.");
    await chooseAndClose("2026-02");
    expect(post).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses", async () => {
    serve([]);
    post.mockRejectedValue(Object.assign(new Error("Bu rol dönem kapatamaz."), { status: 403 }));
    renderWithQuery(<DonemKilitleri now={NOW} />);
    await screen.findByText("Henüz kapatılmış bir dönem yok.");
    await chooseAndClose("2026-02");
    expect(await screen.findByRole("alert")).toHaveTextContent("Bu rol dönem kapatamaz.");
  });

  it("any other failure gets our wording", async () => {
    serve([]);
    post.mockRejectedValue(Object.assign(new Error("Network Error"), { status: undefined }));
    renderWithQuery(<DonemKilitleri now={NOW} />);
    await screen.findByText("Henüz kapatılmış bir dönem yok.");
    await chooseAndClose("2026-02");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Dönem kapatılamadı.");
    expect(alert).not.toHaveTextContent("Network Error");
  });
});

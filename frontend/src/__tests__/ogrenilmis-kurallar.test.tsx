/**
 * Ajanın öğrendikleri — the accountant sees what was learned and can take it back.
 *
 * The API is mocked with the shapes backend/tests/test_learned_rules_api.py pins.
 * What is checked is this component's side: what is listed and whether it is in
 * force, that removing one asks first and then removes it, that a refusal for the
 * role shows the server's reason, and that any other failure uses our wording.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "./dashboard-mocks";

const get = vi.fn();
const del = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: (...a: unknown[]) => get(...a), delete: (...a: unknown[]) => del(...a) },
}));

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true,
    baseCurrency: "TRY", locale: "tr-TR",
  }),
}));

import { OgrenilmisKurallar } from "@/components/smmm/OgrenilmisKurallar";

const kural = (id: string, over: Record<string, unknown> = {}) => ({
  id, anahtar: `reklam gideri meta ${id}`, hesap_kodu: "760", hesap_adi: "Pazarlama Giderleri",
  onay_sayisi: 2, aktif: true, ...over,
});

const serve = (kurallar: unknown[]) =>
  get.mockResolvedValue({ data: { data: { kurallar } } });

const refused = (message: string) => Object.assign(new Error(message), { status: 403 });

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("OgrenilmisKurallar", () => {
  it("lists what was learned, how often, and whether it is in force", async () => {
    serve([kural("a"), kural("b", { aktif: false, onay_sayisi: 1 })]);
    renderWithQuery(<OgrenilmisKurallar />);

    expect(await screen.findByText("reklam gideri meta a")).toBeInTheDocument();
    expect(screen.getByText("Yürürlükte")).toBeInTheDocument();
    expect(screen.getByText("Henüz kural değil")).toBeInTheDocument();
    expect(screen.getByText(/2 düzeltme/)).toBeInTheDocument();
    expect(screen.getByText(/1 düzeltme/)).toBeInTheDocument();
  });

  it("says plainly when nothing has been learned", async () => {
    serve([]);
    renderWithQuery(<OgrenilmisKurallar />);
    expect(await screen.findByText(/Henüz öğrenilen bir şey yok/)).toBeInTheDocument();
  });

  it("asks first, then removes the rule from the list", async () => {
    serve([kural("a"), kural("b")]);
    del.mockResolvedValue({});
    renderWithQuery(<OgrenilmisKurallar />);
    await screen.findByText("reklam gideri meta a");

    fireEvent.click(screen.getByRole("button", { name: /reklam gideri meta a kuralını kaldır/ }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/smmm/kurallar/a"));
    expect(window.confirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByText("reklam gideri meta a")).not.toBeInTheDocument());
    expect(screen.getByText("reklam gideri meta b")).toBeInTheDocument();
  });

  it("does nothing when the person declines the confirmation", async () => {
    serve([kural("a")]);
    (window.confirm as ReturnType<typeof vi.fn>).mockReturnValue(false);
    renderWithQuery(<OgrenilmisKurallar />);
    await screen.findByText("reklam gideri meta a");

    fireEvent.click(screen.getByRole("button", { name: /kuralını kaldır/ }));
    expect(del).not.toHaveBeenCalled();
    expect(screen.getByText("reklam gideri meta a")).toBeInTheDocument();
  });

  it("shows the server's reason when the role may not remove it, and keeps the rule", async () => {
    serve([kural("a")]);
    del.mockRejectedValue(refused("Bu rol öğrenilmiş kuralı silemez."));
    renderWithQuery(<OgrenilmisKurallar />);
    await screen.findByText("reklam gideri meta a");

    fireEvent.click(screen.getByRole("button", { name: /kuralını kaldır/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Bu rol öğrenilmiş kuralı silemez.");
    expect(screen.getByText("reklam gideri meta a")).toBeInTheDocument();
  });

  it("any other failure gets our wording, not a raw error", async () => {
    serve([kural("a")]);
    del.mockRejectedValue(Object.assign(new Error("Network Error"), { status: undefined }));
    renderWithQuery(<OgrenilmisKurallar />);
    await screen.findByText("reklam gideri meta a");

    fireEvent.click(screen.getByRole("button", { name: /kuralını kaldır/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Kural kaldırılamadı.");
    expect(alert).not.toHaveTextContent("Network Error");
  });

  it("says so when the list cannot be loaded", async () => {
    get.mockRejectedValue(new Error("boom"));
    renderWithQuery(<OgrenilmisKurallar />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Öğrenilmiş kurallar yüklenemedi.");
  });
});

/**
 * The company-size question group: short, skippable, and it only ever proposes.
 * The profile is stored by the person's "Onayla"; micro turns the simplified menu on with a one-click undo.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

const { api } = vi.hoisted(() => ({
  api: { getSizeProfile: vi.fn(), saveSizeAnswers: vi.fn(), confirmSizeProfile: vi.fn(), setFocusMode: vi.fn() },
}));
vi.mock("@/lib/api/sizeProfile", () => api);
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { SizeProfileCard } from "@/components/org/SizeProfileCard";
import { renderWithQuery } from "./dashboard-mocks";

const state = (over: Record<string, unknown> = {}) => ({
  monthly_outflow_band: null,
  headcount_band: null,
  has_inhouse_finance: null,
  size_profile: null,
  focus_mode: false,
  suggestion: null,
  options: {
    monthly_outflow_band: [
      { value: "under_500k", label: "500 bin ₺'nin altı" },
      { value: "500k_to_5m", label: "500 bin ₺ – 5 milyon ₺" },
    ],
    headcount_band: [
      { value: "under_10", label: "10'dan az" },
      { value: "50_plus", label: "50 ve üstü" },
    ],
  },
  ...over,
});
const micro = { profile: "micro", decided_by: "volume", disagreement: false };

const pick = async (label: string) => fireEvent.click(await screen.findByLabelText(label));

describe("SizeProfileCard", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getSizeProfile.mockResolvedValue(state());
  });

  it("asks the three questions in plain Turkish, with the honest reason", async () => {
    renderWithQuery(<SizeProfileCard />);
    expect(await screen.findByText("Aylık ödemeleriniz yaklaşık ne kadar?")).toBeInTheDocument();
    expect(screen.getByText("Şirkette kaç kişi çalışıyor?")).toBeInTheDocument();
    expect(screen.getByText("Ön muhasebe / finans işlerine bakan biri var mı?")).toBeInTheDocument();
    expect(screen.getByText(/Ekranları ve onay adımlarını şirketinize göre sadeleştirmek için/)).toBeInTheDocument();
  });

  it("can be skipped, and skipping calls nothing", async () => {
    renderWithQuery(<SizeProfileCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Şimdi değil" }));
    await waitFor(() => expect(screen.queryByText("Şirketinizin büyüklüğü")).not.toBeInTheDocument());
    expect(api.saveSizeAnswers).not.toHaveBeenCalled();
    expect(api.confirmSizeProfile).not.toHaveBeenCalled();
    expect(api.setFocusMode).not.toHaveBeenCalled();
  });

  it("continuing with nothing answered is the same as skipping", async () => {
    renderWithQuery(<SizeProfileCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Devam" }));
    await waitFor(() => expect(screen.queryByText("Şirketinizin büyüklüğü")).not.toBeInTheDocument());
    expect(api.saveSizeAnswers).not.toHaveBeenCalled();
  });

  it("shows nothing to someone who may not decide (the server answers 403)", async () => {
    api.getSizeProfile.mockRejectedValue({ response: { status: 403 } });
    const { container } = renderWithQuery(<SizeProfileCard />);
    await waitFor(() => expect(api.getSizeProfile).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the derived profile for confirmation and stores nothing until it is confirmed", async () => {
    api.saveSizeAnswers.mockResolvedValue(state({ monthly_outflow_band: "under_500k", suggestion: micro }));
    renderWithQuery(<SizeProfileCard />);
    await pick("500 bin ₺'nin altı");
    fireEvent.click(screen.getByRole("button", { name: "Devam" }));
    expect(await screen.findByText("Önerimiz: Mikro işletme")).toBeInTheDocument();
    expect(screen.getByText(/aylık ödeme tutarınıza göre/)).toBeInTheDocument();
    expect(api.saveSizeAnswers).toHaveBeenCalledWith({
      monthly_outflow_band: "under_500k", headcount_band: null, has_inhouse_finance: null,
    });
    expect(api.confirmSizeProfile).not.toHaveBeenCalled();
  });

  it("says which answer decided when headcount and volume disagree", async () => {
    api.saveSizeAnswers.mockResolvedValue(state({
      suggestion: { profile: "micro", decided_by: "volume", disagreement: true },
    }));
    renderWithQuery(<SizeProfileCard />);
    await pick("50 ve üstü");
    await pick("500 bin ₺'nin altı");
    fireEvent.click(screen.getByRole("button", { name: "Devam" }));
    expect(await screen.findByText(/Çalışan sayınız farklı bir profile işaret ediyor; aylık ödeme tutarınız esas alındı/)).toBeInTheDocument();
  });

  it("confirming micro tells the person the menu was simplified, with a one-click undo", async () => {
    api.saveSizeAnswers.mockResolvedValue(state({ suggestion: micro }));
    api.confirmSizeProfile.mockResolvedValue(state({ size_profile: "micro", focus_mode: true, focus_mode_changed: true, suggestion: micro }));
    renderWithQuery(<SizeProfileCard />);
    await pick("10'dan az");
    fireEvent.click(screen.getByRole("button", { name: "Devam" }));
    fireEvent.click(await screen.findByRole("button", { name: "Onayla" }));
    expect(await screen.findByText("Menüyü sadeleştirdik; tüm ekranlar 'Daha fazla' altında")).toBeInTheDocument();
    expect(api.confirmSizeProfile).toHaveBeenCalledWith("micro");

    api.setFocusMode.mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Geri al" }));
    expect(await screen.findByText("Tam menü geri geldi.")).toBeInTheDocument();
    expect(api.setFocusMode).toHaveBeenCalledWith(false);
  });

  it("keeps an explicit focus choice: no 'simplified' notice when the server left focus mode alone", async () => {
    api.saveSizeAnswers.mockResolvedValue(state({ suggestion: micro }));
    api.confirmSizeProfile.mockResolvedValue(state({ size_profile: "micro", focus_mode: false, focus_mode_changed: false, suggestion: micro }));
    renderWithQuery(<SizeProfileCard />);
    await pick("10'dan az");
    fireEvent.click(screen.getByRole("button", { name: "Devam" }));
    fireEvent.click(await screen.findByRole("button", { name: "Onayla" }));
    expect(await screen.findByText("Şirket ölçeği: Mikro işletme")).toBeInTheDocument();
    expect(screen.queryByText(/Menüyü sadeleştirdik/)).not.toBeInTheDocument();
    expect(api.setFocusMode).not.toHaveBeenCalled();
  });

  it("lets the person choose a different profile than the suggestion", async () => {
    api.saveSizeAnswers.mockResolvedValue(state({ suggestion: micro }));
    api.confirmSizeProfile.mockResolvedValue(state({ size_profile: "medium", suggestion: micro }));
    renderWithQuery(<SizeProfileCard />);
    await pick("10'dan az");
    fireEvent.click(screen.getByRole("button", { name: "Devam" }));
    fireEvent.change(await screen.findByRole("combobox"), { target: { value: "medium" } });
    fireEvent.click(screen.getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(api.confirmSizeProfile).toHaveBeenCalledWith("medium"));
  });

  it("shows a profile that is already confirmed as a summary, not as questions", async () => {
    api.getSizeProfile.mockResolvedValue(state({ size_profile: "small" }));
    renderWithQuery(<SizeProfileCard />);
    expect(await screen.findByText("Şirket ölçeği: Küçük işletme")).toBeInTheDocument();
    expect(screen.queryByText("Aylık ödemeleriniz yaklaşık ne kadar?")).not.toBeInTheDocument();
  });

  it("says so when saving fails", async () => {
    api.saveSizeAnswers.mockRejectedValue(new Error("boom"));
    renderWithQuery(<SizeProfileCard />);
    await pick("10'dan az");
    fireEvent.click(screen.getByRole("button", { name: "Devam" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Kaydedilemedi");
  });
});

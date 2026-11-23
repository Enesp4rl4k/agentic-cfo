/**
 * What a company's size sets, and the outside accountant: the materiality threshold card, the briefing
 * recipient card and the accountant's workload.
 *
 * The threshold only ever proposes: nothing applies until a person confirms or sets their own amount.
 * The recipient card names a recipient and sends nothing. The workload lists counts, never another
 * company's data.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

const { api } = vi.hoisted(() => ({
  api: {
    getMateriality: vi.fn(), acknowledgeMateriality: vi.fn(), setMateriality: vi.fn(),
    getBriefingRecipients: vi.fn(), setBriefingToSmmm: vi.fn(), getSmmmWorkload: vi.fn(),
  },
}));
vi.mock("@/lib/api/scale", () => api);
const switchOrg = vi.fn();
vi.mock("@/lib/api/orgs", () => ({ switchOrg: (id: string) => switchOrg(id) }));
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
const update = vi.fn().mockResolvedValue(null);
vi.mock("next-auth/react", () => ({ useSession: () => ({ status: "authenticated", data: { user: {} }, update }) }));
const clearWorkspace = vi.fn();
vi.mock("@/store/companyContext", () => ({ useCompanyContextStore: () => ({ clearWorkspace }) }));

import { BriefingRecipientsCard } from "@/components/org/BriefingRecipientsCard";
import { MaterialityCard } from "@/components/org/MaterialityCard";
import { SmmmWorkload } from "@/components/smmm/SmmmWorkload";
import { renderWithQuery } from "./dashboard-mocks";

const current = {
  threshold_cents: 100_000_00, currency: "TRY", source: "legacy", acknowledged: false,
  acknowledged_at: null, acknowledged_by: null, basis_text: "Sabit tutar.",
};
const proposal = {
  amount_cents: 8_300_00, currency: "TRY", source: "measured", differs_from_current: true,
  basis_text: "Son 6 tam ayın aylık ortalama çıkışı ₺166.667'in %5'i = ₺8.300.",
};
const materiality = (over: Record<string, unknown> = {}) => ({
  current, rule: { ratio: 0.05, floor_cents: 5_000_00, ceiling_cents: 1_000_000_00, legacy_cents: 100_000_00 },
  can_change: true, proposal, history: [], ...over,
});

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  switchOrg.mockReset();
});

describe("MaterialityCard", () => {
  it("says it could not read the threshold instead of drawing nothing", async () => {
    api.getMateriality.mockRejectedValue(new Error("boom"));
    renderWithQuery(<MaterialityCard />);
    expect(await screen.findByText("Onay eşiği verisi alınamadı.")).toBeInTheDocument();
  });

  it("lets an admin read the threshold, the basis and the history but not change it", async () => {
    api.getMateriality.mockResolvedValue(
      materiality({
        can_change: false,
        history: [{ outcome: "acknowledged", decided_at: "2026-03-01T10:00:00Z", reason: null, decided_by: "u1", from_cents: 100_000_00, to_cents: 8_300_00, currency: "TRY" }],
      }),
    );
    renderWithQuery(<MaterialityCard />);
    expect(await screen.findByText(/Onay eşiğini yalnızca şirketin sahibi değiştirebilir/)).toBeInTheDocument();
    expect(screen.getByText("Eşik geçmişi")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Öneriyi onayla ve uygula" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Kendi tutarımı gireyim" })).toBeNull();
  });

  it("shows the fixed amount still in force, the proposal with its basis, and applies nothing by itself", async () => {
    api.getMateriality.mockResolvedValue(materiality());
    renderWithQuery(<MaterialityCard />);
    expect(await screen.findByText(/Şu an geçerli: .*100\.000/)).toBeInTheDocument();
    expect(screen.getByText(/Sabit tutar\. Şirketinizin büyüklüğüne göre henüz hesaplanıp onaylanmadı/)).toBeInTheDocument();
    expect(screen.getByText(/Önerimiz: .*8\.300/)).toBeInTheDocument();
    expect(screen.getByText(/aylık ortalama çıkışı .*%5'i/)).toBeInTheDocument();
    expect(screen.getByText(/hiçbir şey kendiliğinden değişmez/)).toBeInTheDocument();
    expect(api.acknowledgeMateriality).not.toHaveBeenCalled();
    expect(api.setMateriality).not.toHaveBeenCalled();
  });

  it("confirming sends the amount that was shown", async () => {
    api.getMateriality.mockResolvedValue(materiality());
    api.acknowledgeMateriality.mockResolvedValue(
      materiality({ current: { ...current, threshold_cents: 8_300_00, acknowledged: true, source: "measured", basis_text: proposal.basis_text }, proposal: { ...proposal, differs_from_current: false } }),
    );
    renderWithQuery(<MaterialityCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Öneriyi onayla ve uygula" }));
    await waitFor(() => expect(api.acknowledgeMateriality).toHaveBeenCalledWith(8_300_00));
    expect(await screen.findByText(/karar kaydına yazıldı/)).toBeInTheDocument();
    expect(screen.getByText(/Dayanak: Son 6 tam ayın/)).toBeInTheDocument();
  });

  it("says so when the proposal moved while the person was reading", async () => {
    api.getMateriality.mockResolvedValue(materiality());
    api.acknowledgeMateriality.mockRejectedValue({ response: { status: 409 } });
    renderWithQuery(<MaterialityCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Öneriyi onayla ve uygula" }));
    expect(await screen.findByText(/Öneri siz bakarken değişti/)).toBeInTheDocument();
  });

  it("lets the owner set their own amount, in lira, with a reason", async () => {
    api.getMateriality.mockResolvedValue(materiality());
    api.setMateriality.mockResolvedValue(materiality({ proposal: null }));
    renderWithQuery(<MaterialityCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Kendi tutarımı gireyim" }));
    const save = screen.getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    expect(screen.getByText(/5\.000.* ile .*1\.000\.000.* arasında olmalı/)).toBeInTheDocument();
    // outside the bounds, or without a reason, it cannot be saved
    fireEvent.change(screen.getByLabelText("Neden (zorunlu)"), { target: { value: "ortakla konuştuk" } });
    fireEvent.change(screen.getByLabelText("Tutar"), { target: { value: "99999999" } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Tutar"), { target: { value: "30000" } });
    fireEvent.change(screen.getByLabelText("Neden (zorunlu)"), { target: { value: "" } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Neden (zorunlu)"), { target: { value: "ortakla konuştuk" } });
    fireEvent.click(save);
    await waitFor(() => expect(api.setMateriality).toHaveBeenCalledWith(30_000_00, "ortakla konuştuk"));
  });

  it("says that integrity questions never look at the amount", async () => {
    api.getMateriality.mockResolvedValue(materiality());
    renderWithQuery(<MaterialityCard />);
    expect(await screen.findByText(/para birimi, yön, hesap kimliği ve mutabakat soruları tutara bakmaz/)).toBeInTheDocument();
  });

  it("shows an admin the threshold and its history read-only: no proposal, no edit", async () => {
    api.getMateriality.mockResolvedValue(
      materiality({
        can_change: false, proposal: null,
        history: [{ outcome: "owner_override", decided_at: "2026-11-20T10:00:00Z", reason: "büyüdük", decided_by: "Sahip", from_cents: 100_000_00, to_cents: 8_300_00, currency: "TRY" }],
      }),
    );
    renderWithQuery(<MaterialityCard />);
    expect(await screen.findByText(/Şu an geçerli: .*100\.000/)).toBeInTheDocument();
    expect(screen.getByText(/yalnızca şirketin sahibi değiştirebilir/)).toBeInTheDocument();
    expect(screen.getByText(/2026-11-20 · Sahip: .*100\.000.* → .*8\.300/)).toBeInTheDocument();
    expect(screen.getByText(/Neden: büyüdük/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kendi tutarımı gireyim" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Öneriyi onayla ve uygula" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Kaydet" })).toBeNull();
  });
});

describe("BriefingRecipientsCard", () => {
  it("offers the accountant as a recipient, saying delivery stays with the accountant's release", async () => {
    api.getBriefingRecipients.mockResolvedValue({ send_to_smmm: false, has_smmm: true, suggested: true });
    api.setBriefingToSmmm.mockResolvedValue({ send_to_smmm: true, has_smmm: true, suggested: true });
    renderWithQuery(<BriefingRecipientsCard />);
    expect(await screen.findByText(/serbest bırakmasıyla gider/)).toBeInTheDocument();
    expect(screen.getByText(/Şirket ölçeğinize uygun bir öneri/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Bülteni mali müşavirime de gönder"));
    await waitFor(() => expect(api.setBriefingToSmmm).toHaveBeenCalledWith(true));
    expect(await screen.findByText("Tercihiniz kaydedildi.")).toBeInTheDocument();
  });

  it("with no accountant there is no send option, and it says how to get one", async () => {
    api.getBriefingRecipients.mockResolvedValue({ send_to_smmm: false, has_smmm: false, suggested: true });
    renderWithQuery(<BriefingRecipientsCard />);
    expect(await screen.findByText(/mali müşaviri yok/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

describe("SmmmWorkload", () => {
  const two = {
    total_waiting: 4,
    organizations: [
      { org_id: "a", name: "Alfa Gıda", pending_onay: 3, month_to_close: "2026-10", briefings_held: 0, waiting: 4 },
      { org_id: "b", name: "Beta Tekstil", pending_onay: 0, month_to_close: null, briefings_held: 0, waiting: 0 },
    ],
  };

  it("lists each company with what waits, counts only", async () => {
    api.getSmmmWorkload.mockResolvedValue(two);
    renderWithQuery(<SmmmWorkload />);
    expect(await screen.findByText("Alfa Gıda")).toBeInTheDocument();
    expect(screen.getByText("3 kayıt onayınızı bekliyor")).toBeInTheDocument();
    expect(screen.getByText("2026-10 dönemi kapatılmayı bekliyor")).toBeInTheDocument();
    expect(screen.getByText("Bekleyen yok")).toBeInTheDocument();
    expect(screen.getByText("Toplam 4 iş bekliyor")).toBeInTheDocument();
  });

  it("switches into the chosen company before anything of it is shown", async () => {
    api.getSmmmWorkload.mockResolvedValue(two);
    switchOrg.mockResolvedValue({ org_id: "a" });
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, assign }, writable: true });
    renderWithQuery(<SmmmWorkload />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Şirkete geç" }))[0]);
    await waitFor(() => expect(switchOrg).toHaveBeenCalledWith("a"));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/smmm-onay"));
    expect(clearWorkspace).toHaveBeenCalled();
  });

  it("renders nothing for someone who is nobody's accountant", async () => {
    api.getSmmmWorkload.mockResolvedValue({ organizations: [], total_waiting: 0 });
    const { container } = renderWithQuery(<SmmmWorkload />);
    await waitFor(() => expect(api.getSmmmWorkload).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

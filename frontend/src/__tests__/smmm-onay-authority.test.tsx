/**
 * SMMM onay kuyruğu — what a role that may not decide sees, and what a refused
 * decision says.
 *
 * The API is mocked with the shapes backend/tests/test_approval_authority.py
 * pins (`karar_verebilir`, `karar_engeli`; a 403 whose message is the reason).
 * Before, the approve click swallowed every failure ("silently fail for now"),
 * and the page offered buttons the role could never use.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true,
    baseCurrency: "TRY", locale: "tr-TR",
  }),
}));

import SMMMonayPage from "@/app/(dashboard)/smmm-onay/page";

const row = (id: string, over: Record<string, unknown> = {}) => ({
  id, job_id: "j1", kayit_id: id, durum: "bekliyor",
  tx_description: `islem ${id}`, tx_amount_try: 100, tx_tarih: "2026-01-05T00:00:00Z",
  otomatik_hesap_kodu: "770", otomatik_confidence: 0.5, otomatik_yontem: "kural",
  onay_neden: null, duzeltilmis_hesap_kodu: null, duzeltilmis_hesap_adi: null,
  onaylayan_user_id: null, onay_zamani: null, onay_notu: null, orijinal_kayit: null,
  created_at: "2026-01-05T00:00:00Z", karar_verebilir: true, karar_engeli: null, ...over,
});

const stats = { bekliyor: 2, onaylandi: 0, duzeltildi: 0, reddedildi: 0, toplam: 2 };
const OWNER_ONLY = "Bu kayıt için şirket sahibinin (owner) onayı gerekiyor.";

function serve(kayitlar: unknown[]) {
  get.mockImplementation((url: string) =>
    Promise.resolve({ data: { data: url.includes("/stats") ? stats : { kayitlar } } }),
  );
}

const refused = (message: string) => Object.assign(new Error(message), { status: 403 });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("smmm-onay authority", () => {
  it("shows the reason and offers no buttons for an entry this role cannot decide", async () => {
    serve([
      row("a"),
      row("b", { karar_verebilir: false, karar_engeli: OWNER_ONLY }),
    ]);
    render(<SMMMonayPage />);

    expect(await screen.findByText(OWNER_ONLY)).toBeInTheDocument();
    const blocked = screen.getByText("islem b").closest("div.rounded-lg") as HTMLElement;
    const allowed = screen.getByText("islem a").closest("div.rounded-lg") as HTMLElement;

    for (const b of within(blocked).getAllByRole("button", { name: /Onayla|Düzelt|Reddet/ })) {
      expect(b).toBeDisabled();
    }
    expect(within(blocked).getByRole("checkbox")).toBeDisabled();
    for (const b of within(allowed).getAllByRole("button", { name: /Onayla|Düzelt|Reddet/ })) {
      expect(b).toBeEnabled();
    }
  });

  it("select-all skips what the role cannot decide", async () => {
    serve([row("a"), row("b", { karar_verebilir: false, karar_engeli: OWNER_ONLY })]);
    render(<SMMMonayPage />);
    await screen.findByText("islem a");

    fireEvent.click(screen.getByLabelText(/Tümünü Seç/));
    const blocked = screen.getByText("islem b").closest("div.rounded-lg") as HTMLElement;
    const allowed = screen.getByText("islem a").closest("div.rounded-lg") as HTMLElement;
    expect(within(allowed).getByRole("checkbox")).toBeChecked();
    expect(within(blocked).getByRole("checkbox")).not.toBeChecked();
  });

  it("an approve the server refuses shows the server's reason, not a silence", async () => {
    serve([row("a")]);
    post.mockRejectedValue(refused(OWNER_ONLY));
    render(<SMMMonayPage />);
    await screen.findByText("islem a");

    fireEvent.click(screen.getByRole("button", { name: "Onayla" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(OWNER_ONLY);
  });

  it("any other failure gets the page's own wording, not a raw error string", async () => {
    serve([row("a")]);
    post.mockRejectedValue(Object.assign(new Error("Network Error"), { status: undefined }));
    render(<SMMMonayPage />);
    await screen.findByText("islem a");

    fireEvent.click(screen.getByRole("button", { name: "Onayla" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Onaylanamadı.");
    expect(alert).not.toHaveTextContent("Network Error");
  });

  it("a successful approve refreshes the queue", async () => {
    serve([row("a")]);
    post.mockResolvedValue({ data: {} });
    render(<SMMMonayPage />);
    await screen.findByText("islem a");
    const before = get.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(before));
  });
});

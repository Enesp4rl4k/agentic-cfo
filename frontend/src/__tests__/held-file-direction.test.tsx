/**
 * A statement file whose direction nobody could place is ONE question: the person sees what was detected and
 * a few sample rows, answers once, and the answer applies to every row. A debit/credit reading nothing can
 * verify is asked as "is Borç money out of your account?". A remembered answer is listed and can be forgotten
 * by those allowed to; a file with no signal never offers to remember. The file's rows are not asked one by one.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  directionMappingFixture,
  fileQuestionFixture,
  heldRowFixture,
  heldRowsSpies,
  renderWithQuery,
} from "./dashboard-mocks";

vi.mock("@/lib/api/heldRows", async () => (await import("./dashboard-mocks")).heldRowsModule);
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("") }));
vi.mock("@/lib/api/decisionRecords", () => ({ listDecisionEntries: async () => ({ entries: [], total: 0 }) }));

import BekleyenKayitlarPage from "@/app/(dashboard)/bekleyen-kayitlar/page";

const { listHeldRows, listFileQuestions, answerFileDirection, listDirectionMappings, revokeDirectionMapping, getBaseCurrency } =
  heldRowsSpies;

const fileRow = { ...heldRowFixture, id: "f1", description: "Kira", type: null, direction_file: "f9", reasons: ["direction_file_unknown"] };
const convention = {
  ...fileQuestionFixture,
  reason: "convention_unverified",
  options: ["as_read", "inverted", "mixed"],
  question: {
    ...fileQuestionFixture.question,
    mapping: [
      { label: "borc", means: "expense" },
      { label: "alacak", means: "income" },
    ],
  },
};

beforeEach(() => {
  for (const fn of [listHeldRows, listFileQuestions, answerFileDirection, listDirectionMappings, revokeDirectionMapping]) fn.mockClear();
  listHeldRows.mockResolvedValue([fileRow]);
  listFileQuestions.mockResolvedValue({ files: [fileQuestionFixture], canRemember: true });
  listDirectionMappings.mockResolvedValue([]);
  getBaseCurrency.mockResolvedValue({ currency: "TRY", confirmed: true, waiting_for_currency: 0 });
});

describe("Bu ekstrede tutarlar hangi yönde?", () => {
  it("asks once for the file, showing the detected columns and sample rows, not once per row", async () => {
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("Bu ekstrede tutarlar hangi yönde?")).toBeInTheDocument();
    expect(screen.getByText("2 satır bekliyor")).toBeInTheDocument();
    expect(screen.getByText(/tarih \(tarih\) · açıklama \(açıklama\) · tutar \(tutar\)/)).toBeInTheDocument();
    expect(screen.getByText("Elektrik")).toBeInTheDocument(); // a sample row
    expect(screen.queryByRole("button", { name: "Olduğu gibi kabul et" })).toBeNull(); // the file's rows are not listed one by one
    expect(screen.queryByText("İncelemenizi bekleyen kayıt yok.")).toBeNull();
  });

  it("says honestly that a file with no signal cannot be split, and never offers to remember", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText(/sistem giriş ile çıkışı ayıramaz ve tahmin etmez/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Bu ekstre biçimi için cevabımı hatırla")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Bu dosyada yalnızca çıkış (gider) var" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "only_expense", remember: false }),
    );
    expect(answerFileDirection).toHaveBeenCalledTimes(1);
  });

  it("leaves the rows to be corrected one by one when asked", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    await user.click(await screen.findByRole("button", { name: "Satırları tek tek düzelteceğim" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "mixed", remember: false }),
    );
  });

  it("asks whether Borç is money out of the account, showing how it was read and sample descriptions", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({ files: [convention], canRemember: true });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText('Bu ekstrede "borc" hesabınızdan ÇIKAN para mı?')).toBeInTheDocument();
    expect(screen.getByText(/Okunan: borc → Gider · alacak → Gelir/)).toBeInTheDocument();
    expect(screen.getByText("Kira")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hayır, tersi" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "inverted", remember: true }),
    );
  });

  it("does not remember when the box is cleared, or when the person may not make a standing rule", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({ files: [convention], canRemember: true });
    renderWithQuery(<BekleyenKayitlarPage />);
    await user.click(await screen.findByLabelText("Bu ekstre biçimi için cevabımı hatırla"));
    await user.click(screen.getByRole("button", { name: "Evet, sütunların dediği gibi" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "as_read", remember: false }),
    );
  });

  it("hides the remember box and explains why for a writer without authority", async () => {
    listFileQuestions.mockResolvedValue({ files: [convention], canRemember: false });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText(/sahip, yönetici ya da mali müşavir yetkisi ister/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Bu ekstre biçimi için cevabımı hatırla")).toBeNull();
  });

  it("explains a balance contradiction in its own words", async () => {
    listFileQuestions.mockResolvedValue({
      files: [{ ...fileQuestionFixture, reason: "balance_contradicts", options: ["as_read", "balance", "mixed"] }],
      canRemember: true,
    });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText(/Bakiye sütunu, tutar sütunlarından okunan yönün tersini gösteriyor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bakiyenin gösterdiği gibi" })).toBeInTheDocument();
  });
});

describe("which account, and the sign question", () => {
  it("says an answer cannot be remembered for a file that names no account, and offers no box", async () => {
    listFileQuestions.mockResolvedValue({ files: [{ ...convention, identity: false }], canRemember: true });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText(/hangi banka hesabına ait olduğunu söylemiyor/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Bu ekstre biçimi için cevabımı hatırla")).toBeNull();
  });

  it("asks whether minus is out and plus is in, with both readings' totals, and remembers per format without an account", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({
      files: [
        {
          ...fileQuestionFixture,
          reason: "sign_unconfirmed",
          identity: false,
          options: ["sign_correct", "sign_inverted", "mixed"],
          question: {
            ...fileQuestionFixture.question,
            totals: { as_read: { income: 270000, expense: 30000 }, inverted: { income: 30000, expense: 270000 } },
            uniform: false,
          },
        },
      ],
      canRemember: true,
    });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("Bu dosyada eksi tutarlar çıkış, artı tutarlar giriş mi?")).toBeInTheDocument();
    expect(screen.getByText(/Eksi çıkışsa: 2\.700,00 giriş, 300,00 çıkış\. Tersiyse: 300,00 giriş, 2\.700,00 çıkış\./)).toBeInTheDocument();
    expect(screen.getByText("Elektrik")).toBeInTheDocument(); // the preview rows
    // the sign is a fact about the export's format, so the box is offered even when the file names no account
    expect(screen.getByLabelText("Bu ekstre biçimi için cevabımı hatırla")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hayır, tersi: artı = çıkan (gider), eksi = giren ya da iade" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "sign_inverted", remember: true }),
    );
  });

  it("confirms the signs with the same one question", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({
      files: [{ ...fileQuestionFixture, reason: "sign_unconfirmed", options: ["sign_correct", "sign_inverted", "mixed"] }],
      canRemember: true,
    });
    renderWithQuery(<BekleyenKayitlarPage />);
    await user.click(await screen.findByRole("button", { name: "Tutarların işareti doğru: eksi = çıkan, artı = giren" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "sign_correct", remember: true }),
    );
  });

  it("says plainly that a file with one sign only has nothing to check the signs against", async () => {
    listFileQuestions.mockResolvedValue({
      files: [{ ...fileQuestionFixture, reason: "sign_unconfirmed", options: ["sign_correct", "sign_inverted", "mixed"],
        question: { ...fileQuestionFixture.question, uniform: true } }],
      canRemember: true,
    });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText(/tüm tutarlar aynı işaretli/)).toBeInTheDocument();
  });
});

describe("the same header words, another source: the earlier answer is shown, not applied", () => {
  const signFile = {
    ...fileQuestionFixture,
    reason: "sign_unconfirmed",
    identity: false,
    options: ["sign_correct", "sign_inverted", "mixed"],
    previous: { answer: "sign_correct", columns: "tarih, açıklama, tutar", account: null, same_account: false, created_at: null },
  };

  it("names the earlier answer, pre-selects it as one click, and records nothing standing unless asked", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({ files: [signFile], canRemember: true });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByTestId("previous-answer")).toHaveTextContent(
      /Aynı başlıklı önceki dosyada \(tarih, açıklama, tutar\) "Tutarların işareti doğru: eksi = çıkan, artı = giren" demiştiniz; bu dosya için de geçerli mi\?/,
    );
    const buttons = screen.getAllByRole("button").filter((b) => b.hasAttribute("aria-pressed"));
    expect(buttons[0]).toHaveTextContent("Evet, öncekiyle aynı: Tutarların işareti doğru");
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    await user.click(buttons[0]);
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "sign_correct", remember: true }),
    );
  });

  it("offers a standing rule for files that name no account, as an explicit tick", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({ files: [signFile], canRemember: true });
    renderWithQuery(<BekleyenKayitlarPage />);
    await user.click(await screen.findByLabelText(/Bu başlıkla gelen, hesabı belli olmayan dosyalar hep böyle/));
    await user.click(screen.getByRole("button", { name: /Hayır, tersi/ }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({
        job_id: "j9", file_key: "f9", answer: "sign_inverted", remember: true, standing: true,
      }),
    );
  });

  it("lists a standing rule and an override by a balance chain where remembered answers are shown", async () => {
    listFileQuestions.mockResolvedValue({ files: [], canRemember: true });
    listHeldRows.mockResolvedValue([]);
    listDirectionMappings.mockResolvedValue([
      { ...directionMappingFixture, standing: true, flagged_at: "2026-04-01T10:00:00Z", flagged_note: "the balance chain verifies minus = out" },
    ]);
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText(/hesabı belli olmayan dosyalar için kalıcı kural/)).toBeInTheDocument();
    expect(screen.getByText(/Bir bakiye zinciri bu cevabı geçersiz kıldı: the balance chain verifies minus = out/)).toBeInTheDocument();
  });
});

describe("one balance step is a suggestion, not a proof", () => {
  it("pre-selects the suggested reading and says why it is only a suggestion", async () => {
    listFileQuestions.mockResolvedValue({
      files: [{
        ...fileQuestionFixture, reason: "sign_unconfirmed", options: ["sign_correct", "sign_inverted", "mixed"],
        question: { ...fileQuestionFixture.question, suggested: { answer: "sign_correct", reason: "single_step" } },
      }],
      canRemember: true,
    });
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByTestId("suggested-answer")).toHaveTextContent("Tek bir bakiye adımı bu yönü destekliyor");
    const pressed = screen.getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);
    expect(pressed[0]).toHaveTextContent("Tutarların işareti doğru");
  });
});

describe("hatırlanan ekstre yönleri", () => {
  it("lists a remembered answer and forgets it on request", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({ files: [], canRemember: true });
    listHeldRows.mockResolvedValue([]);
    listDirectionMappings.mockResolvedValue([directionMappingFixture]);
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("Hatırlanan ekstre yönleri")).toBeInTheDocument();
    expect(screen.getByText(/tarih, açıklama, tutar/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Unut" }));
    await waitFor(() => expect(revokeDirectionMapping).toHaveBeenCalledWith("m9"));
  });

  it("does not offer to forget to someone who may not", async () => {
    listFileQuestions.mockResolvedValue({ files: [], canRemember: false });
    listHeldRows.mockResolvedValue([]);
    listDirectionMappings.mockResolvedValue([directionMappingFixture]);
    renderWithQuery(<BekleyenKayitlarPage />);
    await screen.findByText("Hatırlanan ekstre yönleri");
    expect(screen.queryByRole("button", { name: "Unut" })).toBeNull();
  });

  it("says that nothing is remembered instead of showing a blank", async () => {
    listFileQuestions.mockResolvedValue({ files: [], canRemember: true });
    listHeldRows.mockResolvedValue([]);
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("İncelemenizi bekleyen kayıt yok.")).toBeInTheDocument();
    expect(await screen.findByText("Hatırlanan ekstre yönü yok. Bir ekstrenin yönünü hatırlamayı seçtiğinizde burada listelenir ve istediğinizde unutabilirsiniz.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unut" })).toBeNull();
  });

  it("says that the remembered answers could not be read", async () => {
    listFileQuestions.mockResolvedValue({ files: [], canRemember: true });
    listHeldRows.mockResolvedValue([]);
    listDirectionMappings.mockRejectedValue(new Error("boom"));
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("Hatırlanan ekstre yönleri verisi alınamadı.")).toBeInTheDocument();
  });

  it("opens the decision history of one remembered answer (remembered, overridden, revoked), read-only", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue({ files: [], canRemember: false });
    listHeldRows.mockResolvedValue([]);
    listDirectionMappings.mockResolvedValue([directionMappingFixture]);
    renderWithQuery(<BekleyenKayitlarPage />);
    await screen.findByText("Hatırlanan ekstre yönleri");
    expect(screen.getByRole("button", { name: "Karar geçmişi" })).toHaveAttribute("aria-expanded", "false");
    await user.click(screen.getByRole("button", { name: "Karar geçmişi" }));
    expect(screen.getByRole("button", { name: "Karar geçmişi" })).toHaveAttribute("aria-expanded", "true");
  });
});

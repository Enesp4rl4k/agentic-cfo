/**
 * A statement file whose direction nobody could place is ONE question: the person sees what was detected and
 * a few sample rows, answers once, and the answer applies to every row. A remembered answer is listed and
 * can be forgotten. The file's rows are not asked about one by one.
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

import BekleyenKayitlarPage from "@/app/(dashboard)/bekleyen-kayitlar/page";

const { listHeldRows, listFileQuestions, answerFileDirection, listDirectionMappings, revokeDirectionMapping, getBaseCurrency } =
  heldRowsSpies;

const fileRow = { ...heldRowFixture, id: "f1", description: "Kira", type: null, direction_file: "f9", reasons: ["direction_file_unknown"] };

beforeEach(() => {
  for (const fn of [listHeldRows, listFileQuestions, answerFileDirection, listDirectionMappings, revokeDirectionMapping]) fn.mockClear();
  listHeldRows.mockResolvedValue([fileRow]);
  listFileQuestions.mockResolvedValue([fileQuestionFixture]);
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

  it("sends the answer once for the file, remembered by default", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    await user.click(await screen.findByRole("button", { name: "Tutarların hepsi çıkış (gider)" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "all_expense", remember: true }),
    );
    expect(answerFileDirection).toHaveBeenCalledTimes(1);
  });

  it("does not remember when the box is cleared, and never remembers a mixed answer", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    await user.click(await screen.findByLabelText("Bu ekstre biçimi için cevabımı hatırla"));
    await user.click(screen.getByRole("button", { name: "Tutarların hepsi giriş (gelir)" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenCalledWith({ job_id: "j9", file_key: "f9", answer: "all_income", remember: false }),
    );
    await user.click(screen.getByLabelText("Bu ekstre biçimi için cevabımı hatırla"));
    await user.click(screen.getByRole("button", { name: "Karışık: satırları tek tek karara bağlayacağım" }));
    await waitFor(() =>
      expect(answerFileDirection).toHaveBeenLastCalledWith({ job_id: "j9", file_key: "f9", answer: "mixed", remember: false }),
    );
  });

  it("explains a balance contradiction in its own words", async () => {
    listFileQuestions.mockResolvedValue([
      { ...fileQuestionFixture, reason: "balance_contradicts", options: ["as_read", "balance", "mixed"] },
    ]);
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText(/Bakiye sütunu, tutar sütunlarından okunan yönün tersini gösteriyor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bakiyenin gösterdiği gibi" })).toBeInTheDocument();
  });
});

describe("hatırlanan ekstre yönleri", () => {
  it("lists a remembered answer and forgets it on request", async () => {
    const user = userEvent.setup();
    listFileQuestions.mockResolvedValue([]);
    listHeldRows.mockResolvedValue([]);
    listDirectionMappings.mockResolvedValue([directionMappingFixture]);
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("Hatırlanan ekstre yönleri")).toBeInTheDocument();
    expect(screen.getByText(/tarih, açıklama, tutar/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Unut" }));
    await waitFor(() => expect(revokeDirectionMapping).toHaveBeenCalledWith("m9"));
  });

  it("shows nothing when no answer is remembered", async () => {
    listFileQuestions.mockResolvedValue([]);
    listHeldRows.mockResolvedValue([]);
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("İncelemenizi bekleyen kayıt yok.")).toBeInTheDocument();
    expect(screen.queryByText("Hatırlanan ekstre yönleri")).toBeNull();
  });
});

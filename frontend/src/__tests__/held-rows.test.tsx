/**
 * Rows the system would not book alone: the person sees where each came from and why it waits,
 * accepts it as it is, corrects what was the problem, or rejects it. Unknown confidence is never a number.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { heldNoCurrencyFixture, heldRowFixture, heldRowsSpies, renderWithQuery } from "./dashboard-mocks";

vi.mock("@/lib/api/heldRows", async () => (await import("./dashboard-mocks")).heldRowsModule);
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("") }));

import BekleyenKayitlarPage from "@/app/(dashboard)/bekleyen-kayitlar/page";
import { HeldRowsLink } from "@/components/held-rows/HeldRowsLink";

const { listHeldRows, releaseHeldRows, rejectHeldRows, getBaseCurrency, confirmBaseCurrency } = heldRowsSpies;

beforeEach(() => {
  for (const fn of [listHeldRows, releaseHeldRows, rejectHeldRows, getBaseCurrency, confirmBaseCurrency]) fn.mockClear();
  listHeldRows.mockResolvedValue([heldRowFixture, heldNoCurrencyFixture]);
  getBaseCurrency.mockResolvedValue({ currency: null, confirmed: false, waiting_for_currency: 1 });
});

describe("İncelemenizi bekleyen kayıtlar", () => {
  it("shows the source document and the reason in plain Turkish, never a percentage for an unscored row", async () => {
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("Elektrik faturası")).toBeInTheDocument();
    expect(screen.getAllByText(/mart\.csv/).length).toBe(2);
    expect(screen.getByText("güven bilinmiyor")).toBeInTheDocument();
    expect(screen.getByText("para birimi bilinmiyor")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/%\s?\d/);
  });

  it("accepts a row as it is, and refuses to when something is missing", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    await screen.findByText("Elektrik faturası");
    const accept = screen.getAllByRole("button", { name: "Olduğu gibi kabul et" });
    expect(accept[1]).toBeDisabled(); // no currency: needs a correction first
    await user.click(accept[0]);
    await waitFor(() => expect(releaseHeldRows).toHaveBeenCalledWith({ ids: ["h1"] }));
  });

  it("corrects the missing currency and accepts, sending only what was fixed", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    await screen.findByText("Kira");
    await user.click(screen.getByRole("button", { name: "Düzelt ve kabul et" }));
    const fields = screen.getAllByLabelText("Para birimi");
    await user.type(fields[fields.length - 1], "TRY");
    await user.click(screen.getAllByRole("button", { name: "Düzelt ve kabul et" })[0]);
    await waitFor(() =>
      expect(releaseHeldRows).toHaveBeenCalledWith({ ids: ["h2"], corrections: { h2: { currency: "TRY" } } }),
    );
  });

  it("rejects a row", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    await screen.findByText("Elektrik faturası");
    await user.click(screen.getAllByRole("button", { name: "Reddet" })[0]);
    await waitFor(() => expect(rejectHeldRows).toHaveBeenCalledWith({ ids: ["h1"] }));
  });

  it("asks for the company currency once, because rows wait for it", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BekleyenKayitlarPage />);
    await screen.findByText("Şirketinizin para birimi nedir?");
    await user.type(screen.getAllByLabelText("Para birimi")[0], "try");
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(confirmBaseCurrency).toHaveBeenCalledWith("TRY"));
  });

  it("says when nothing waits", async () => {
    listHeldRows.mockResolvedValue([]);
    renderWithQuery(<BekleyenKayitlarPage />);
    expect(await screen.findByText("İncelemenizi bekleyen kayıt yok.")).toBeInTheDocument();
  });
});

describe("the link from the upload, the radar and the approvals page", () => {
  it("says how many rows wait and links to the list", async () => {
    renderWithQuery(<HeldRowsLink />);
    const link = await screen.findByRole("link", { name: "2 kayıt incelemenizi bekliyor" });
    expect(link).toHaveAttribute("href", "/bekleyen-kayitlar");
  });

  it("carries the job when it is the result of one upload", async () => {
    renderWithQuery(<HeldRowsLink jobId="j1" />);
    const link = await screen.findByRole("link", { name: "Bu yüklemeden 2 kayıt incelemenizi bekliyor" });
    expect(link).toHaveAttribute("href", "/bekleyen-kayitlar?job=j1");
  });

  it("renders nothing when no row waits", async () => {
    listHeldRows.mockResolvedValue([]);
    const { container } = renderWithQuery(<HeldRowsLink />);
    await waitFor(() => expect(listHeldRows).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

/**
 * "Bu ekstreler aynı banka hesabına mı ait?": the card on /onay. Statements nothing links are never
 * added together; the owner or an admin answers, everyone else sees that it waits.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const listAccountQuestions = vi.fn();
const answerAccountQuestion = vi.fn();
vi.mock("@/lib/api/accountQuestions", () => ({
  listAccountQuestions: (...a: unknown[]) => listAccountQuestions(...a),
  answerAccountQuestion: (...a: unknown[]) => answerAccountQuestion(...a),
}));
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { AccountQuestions } from "@/components/approvals/AccountQuestions";

const question = {
  question: "Bu ekstreler aynı banka hesabına mı ait?",
  a: { name: "ocak.pdf", identity_hint: "IBAN ****1326", as_of: "2026-01-31", balance_cents: 90_000_00, currency: "TRY" },
  b: { name: "mart.pdf", as_of: "2026-03-31", balance_cents: 60_000_00, currency: "TRY" },
  job_ids_a: ["j1"],
  job_ids_b: ["j2"],
};

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountQuestions />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  listAccountQuestions.mockReset();
  answerAccountQuestion.mockReset();
  answerAccountQuestion.mockResolvedValue(undefined);
});

describe("Hesap soruları", () => {
  it("shows nothing when no statements are in doubt", async () => {
    listAccountQuestions.mockResolvedValue({ questions: [], canDecide: true });
    const { container } = show();
    await waitFor(() => expect(listAccountQuestions).toHaveBeenCalled());
    expect(container.textContent).toBe("");
    expect(screen.queryByTestId("account-question")).toBeNull();
  });

  it("lists each pair with both balances and sends the owner's answer", async () => {
    listAccountQuestions.mockResolvedValue({ questions: [question], canDecide: true });
    show();
    const card = await screen.findByTestId("account-question");
    expect(card.textContent).toContain("ocak.pdf");
    expect(card.textContent).toContain("mart.pdf");
    expect(card.textContent).toContain("IBAN ****1326"); // masked: never the whole number
    fireEvent.click(screen.getByRole("button", { name: "Aynı hesap" }));
    await waitFor(() => expect(answerAccountQuestion).toHaveBeenCalledWith(question, "same"));
    fireEvent.click(screen.getByRole("button", { name: "Farklı hesaplar" }));
    await waitFor(() => expect(answerAccountQuestion).toHaveBeenCalledWith(question, "different"));
  });

  it("offers no buttons to someone who may not decide, and says whose decision it is", async () => {
    listAccountQuestions.mockResolvedValue({ questions: [question], canDecide: false });
    show();
    await screen.findByTestId("account-question");
    expect(screen.queryByRole("button", { name: "Aynı hesap" })).toBeNull();
    expect(screen.getByText(/şirket sahibi ya da yönetici/)).toBeTruthy();
  });
});

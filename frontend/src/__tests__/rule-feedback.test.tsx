/**
 * Plan v5 §F0 — the user sees that their corrections stick.
 *
 * After a standing rule is saved, the analyses it changes are offered for a
 * rerun (their dashboards were derived from the old categories). A sealed or
 * in-review analysis refuses with 409 and is reported as skipped. Rows whose
 * category came from the user's rule carry a badge.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { client } = vi.hoisted(() => ({ client: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock("@/lib/api/client", () => ({ apiClient: client }));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
  }),
}));

import { getMessages } from "@/lib/i18n";
import { RuleRerunBanner, UserRuleBadge } from "@/components/transactions/RuleFeedback";

const tr = getMessages("tr").ruleFeedback;

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

afterEach(() => vi.clearAllMocks());

describe("RuleRerunBanner", () => {
  it("renders nothing when the rule changes no analysis", () => {
    const { container } = wrap(<RuleRerunBanner jobIds={[]} onDismiss={() => {}} />);
    expect(container.textContent).toBe("");
  });

  it("reruns every affected analysis", async () => {
    client.post.mockResolvedValue({ data: { data: { status: "queued" } } });
    wrap(<RuleRerunBanner jobIds={["j1", "j2"]} onDismiss={() => {}} />);

    expect(screen.getByText(tr.bannerTitle.replace("{n}", "2"))).toBeTruthy();
    fireEvent.click(screen.getByText(tr.rerun));

    await screen.findByText(tr.queued.replace("{n}", "2"));
    expect(client.post.mock.calls.map((c) => c[0]).sort()).toEqual([
      "/analysis/j1/rerun",
      "/analysis/j2/rerun",
    ]);
  });

  it("reports a refused (sealed / in-review) analysis as skipped", async () => {
    client.post
      .mockResolvedValueOnce({ data: { data: { status: "queued" } } })
      .mockRejectedValueOnce(new Error("409"));
    wrap(<RuleRerunBanner jobIds={["j1", "j2"]} onDismiss={() => {}} />);

    fireEvent.click(screen.getByText(tr.rerun));

    await waitFor(() =>
      expect(screen.getByText(tr.partial.replace("{ok}", "1").replace("{n}", "2"))).toBeTruthy(),
    );
  });
});

describe("UserRuleBadge", () => {
  it("marks rule- and hand-decided categories, and nothing else", () => {
    const { rerender } = wrap(<UserRuleBadge source="user_rule" />);
    expect(screen.getByText(tr.badgeRule)).toBeTruthy();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <UserRuleBadge source="user_edit" />
      </QueryClientProvider>,
    );
    expect(screen.getByText(tr.badgeEdit)).toBeTruthy();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <UserRuleBadge source={null} />
      </QueryClientProvider>,
    );
    expect(screen.queryByText(tr.badgeRule)).toBeNull();
    expect(screen.queryByText(tr.badgeEdit)).toBeNull();
  });
});

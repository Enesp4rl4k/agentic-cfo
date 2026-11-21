/**
 * A result page opened while its run is still going: it says the run is going and reads the result
 * by itself when the run stops. It used to ask for the dashboard at once, get "none", keep that for the
 * life of the page, and show "no data" (or stay blank) with the run finishing behind it.
 */
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderWithQuery } from "./dashboard-mocks";

const { cfo, jobParam } = vi.hoisted(() => ({
  cfo: { getJobStatus: vi.fn(), getDashboard: vi.fn() },
  jobParam: { value: "job-1" as string | null },
}));
vi.mock("@/lib/api/cfo", async () => ({ ...(await vi.importActual<object>("@/lib/api/cfo")), ...cfo }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(jobParam.value ? `job=${jobParam.value}` : ""),
  usePathname: () => "/pnl",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);
vi.mock("@/lib/api/heldRows", () => ({ listHeldRows: async () => [] }));
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { useDashboard } from "@/hooks/useCFO";
import PnLPage from "@/app/(dashboard)/pnl/page";
import { getMessages } from "@/lib/i18n";

const copy = getMessages("tr").heldAnalysis.pnl;
const job = (status: string, over: Record<string, unknown> = {}) => ({
  job_id: "job-1", status, filename: "f.csv", awaiting_review: status === "awaiting_review",
  min_confidence: null, logs: [], error: null, ...over,
});
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
);

beforeEach(() => {
  vi.clearAllMocks();
  jobParam.value = "job-1";
});

describe("useDashboard", () => {
  it("does not ask for the dashboard while the run is going, and reads it once the run has finished", async () => {
    cfo.getJobStatus.mockResolvedValueOnce(job("analyzing")).mockResolvedValue(job("completed"));
    cfo.getDashboard.mockResolvedValue({ pnl: { revenue: 1 } });
    const { result } = renderHook(() => useDashboard("job-1"), { wrapper });
    await waitFor(() => expect(result.current.running).toBe(true));
    expect(result.current.isLoading).toBe(true);        // not "no data"
    expect(cfo.getDashboard).not.toHaveBeenCalled();
    // The status poll (every 2 s) sees the end; the dashboard is read then, with no reload.
    await waitFor(() => expect(result.current.data).toEqual({ pnl: { revenue: 1 } }), { timeout: 8000 });
    expect(result.current.running).toBe(false);
    expect(cfo.getDashboard).toHaveBeenCalledTimes(1);
  });

  it("reads the dashboard straight away for a run that already finished", async () => {
    cfo.getJobStatus.mockResolvedValue(job("completed"));
    cfo.getDashboard.mockResolvedValue({ pnl: {} });
    const { result } = renderHook(() => useDashboard("job-1"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(cfo.getJobStatus).toHaveBeenCalledTimes(1);
  });

  it("still tries the dashboard when the run's status cannot be read", async () => {
    cfo.getJobStatus.mockRejectedValue(new Error("403"));
    cfo.getDashboard.mockResolvedValue({ pnl: {} });
    const { result } = renderHook(() => useDashboard("job-1"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
  });
});

describe("/pnl for a run that is not a result yet", () => {
  it("says the analysis is running instead of 'no data'", async () => {
    cfo.getJobStatus.mockResolvedValue(job("analyzing"));
    renderWithQuery(<PnLPage />);
    expect(await screen.findByText(copy.runningTitle)).toBeInTheDocument();
    expect(screen.getByText(copy.runningBody)).toBeInTheDocument();
    expect(cfo.getDashboard).not.toHaveBeenCalled();
  });

  it("says a held run waits for approval, with the link to the approvals, when no figure exists yet", async () => {
    cfo.getJobStatus.mockResolvedValue(job("awaiting_review"));
    cfo.getDashboard.mockRejectedValue(new Error("404"));
    renderWithQuery(<PnLPage />);
    // The dashboard read retries twice (1 s, 2 s) before it is believed to be missing.
    expect(await screen.findByText(copy.heldTitle, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.heldCta })).toHaveAttribute("href", "/onay");
  });

  it("gives the reason a run failed", async () => {
    cfo.getJobStatus.mockResolvedValue(job("failed", { error: "Tarih sütunu bulunamadı." }));
    cfo.getDashboard.mockRejectedValue(new Error("404"));
    renderWithQuery(<PnLPage />);
    expect(await screen.findByText(copy.failedTitle, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByText("Tarih sütunu bulunamadı.")).toBeInTheDocument();
  });
});

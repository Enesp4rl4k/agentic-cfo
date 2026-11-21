/**
 * Where every row of an upload went: "N satır okundu: A kaydedildi, B kararınızı bekliyor, C özet satırı atlandı",
 * the skipped lines viewable, a count that does not add up said out loud. Nothing disappears unseen.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "./dashboard-mocks";

vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
import { IngestCounts } from "@/components/held-rows/IngestCounts";

const base = { rows_read: 8, processed: 5, held: 1, summary_lines_skipped: 2, skipped_lines: [] as Array<{ description: string; date: string }> };

describe("IngestCounts", () => {
  it("says how many rows were read and where each went", () => {
    renderWithQuery(<IngestCounts ingest={base} />);
    expect(screen.getByText("8 satır okundu: 5 kaydedildi, 1 kararınızı bekliyor, 2 özet satırı atlandı")).toBeInTheDocument();
  });

  it("lists the skipped summary lines and the transfer postings", () => {
    renderWithQuery(
      <IngestCounts
        ingest={{ ...base, account_lines_skipped: 1, skipped_lines: [{ description: "Devreden Bakiye", date: "" }, { description: "Toplam", date: "05.01.2026" }] }}
      />,
    );
    expect(screen.getByText(/1 geçiş\/kapanış kaydı atlandı/)).toBeInTheDocument();
    expect(screen.getByText("Atlanan özet satırları")).toBeInTheDocument();
    expect(screen.getByText("Devreden Bakiye")).toBeInTheDocument();
    expect(screen.getByText("05.01.2026 · Toplam")).toBeInTheDocument();
  });

  it("raises an alert when rows could not be accounted for, and says another reader was used", () => {
    renderWithQuery(<IngestCounts ingest={{ ...base, unaccounted: 3, reader_fallback: true }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("3 satır hesaba katılamadı");
    expect(screen.getByText(/alternatif okuyucu kullanıldı/)).toBeInTheDocument();
  });

  it("renders nothing for an upload that reported no row counts", () => {
    const { container } = renderWithQuery(<IngestCounts ingest={{ processed: 2 }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("IngestCounts: balance verification of a text statement", () => {
  it("says a text statement could not be verified against its balance, and never presents it as reconciled", () => {
    renderWithQuery(<IngestCounts ingest={{ ...base, balance_check: "unverified" }} />);
    expect(screen.getByText(/Bakiye ile doğrulanamadı/)).toBeInTheDocument();
    expect(screen.queryByText(/Bakiye zinciriyle doğrulandı/)).toBeNull();
  });

  it("says when the balance chain verified it", () => {
    renderWithQuery(<IngestCounts ingest={{ ...base, balance_check: "verified" }} />);
    expect(screen.getByText("Bakiye zinciriyle doğrulandı.")).toBeInTheDocument();
  });
});

/**
 * The head every operational page shares: the loop step as its eyebrow, the title as the h1.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    hasTrPack: true,
    focusMode: false,
    baseCurrency: "TRY",
    locale: "tr-TR",
  }),
}));

import { PageHead } from "@/components/brand-app/PageHead";
import { brand } from "@/lib/branding";

describe("PageHead", () => {
  it("names the step of the weekly loop above the title", () => {
    render(<PageHead step={2} title="Onay Kuyruğu" subtitle="Tek tıkla onay" />);
    expect(screen.getByText("III · DECIDE")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Onay Kuyruğu");
    expect(screen.getByText("Tek tıkla onay")).toBeInTheDocument();
  });

  it("shows no eyebrow for a page outside the loop", () => {
    render(<PageHead title="Ayarlar" />);
    expect(screen.queryByText(/OBSERVE|ORIENT|DECIDE|ACT/)).toBeNull();
  });

  it("renders its own actions on the right", () => {
    render(<PageHead title="Raporlar" aside={<button type="button">Yenile</button>} />);
    expect(screen.getByRole("button", { name: "Yenile" })).toBeInTheDocument();
  });
});

describe("product name", () => {
  it("defaults to Tiphys when no name is configured", () => {
    expect(brand.name).toBe("Tiphys");
  });
});

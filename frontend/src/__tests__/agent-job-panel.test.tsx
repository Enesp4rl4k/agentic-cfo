/**
 * Step list — a step whose status is "success" shows as done. The second `??`
 * in `log.ok ?? a === "ok" ?? a === "success"` never ran (a boolean is never
 * nullish), so such steps kept spinning.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/ui/lottie-player", () => ({ LottiePlayer: () => null }));
vi.mock("@/hooks/useI18n", () => ({
  useI18n: () => ({ t: { reviewQueue: { status: "ONAY_BEKLIYOR", heldNotice: "YAZILMADI" } } }),
}));

import { AgentJobPanel } from "@/components/ui/agent-job-panel";

const steps = (status: string) => [{ step: "risk_summary", status }] as never;

describe("AgentJobPanel steps", () => {
  it.each(["ok", "success"])("marks a step with status %s as done", (status) => {
    render(<AgentJobPanel status="running" progress={50} error={null} logs={steps(status)} />);
    expect(screen.getByText("Risk özeti").parentElement?.textContent).toContain("✓");
  });

  it("marks a failed step as failed", () => {
    render(<AgentJobPanel status="running" progress={50} error={null} logs={steps("error")} />);
    expect(screen.getByText("Risk özeti").parentElement?.textContent).toContain("✕");
  });

  it("says a held result is ready and awaiting the owner, not still running", () => {
    render(<AgentJobPanel status="awaiting_review" progress={100} error={null} logs={[] as never} />);
    expect(screen.getByText("ONAY_BEKLIYOR")).toBeTruthy();
    expect(screen.getByText("YAZILMADI")).toBeTruthy();
  });
});

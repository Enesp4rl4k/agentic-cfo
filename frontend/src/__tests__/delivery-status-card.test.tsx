/**
 * Delivery status of the notification destinations: per destination host the last success, the last failure
 * and the human reason. Read-only, owner and admin. Never a URL; an unknown reason has a visible fallback.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { useSession } from "next-auth/react";

const { api } = vi.hoisted(() => ({ api: { getDeliveryStatus: vi.fn() } }));
vi.mock("@/lib/api/deliveryStatus", () => api);
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { DeliveryStatusCard } from "@/components/org/DeliveryStatusCard";
import { renderWithQuery } from "./dashboard-mocks";

const as = (role: string) =>
  vi.mocked(useSession).mockReturnValue({
    data: { user: { id: "u", email: "o@x.com", role, orgId: "o" }, accessToken: "tok" },
    status: "authenticated",
  } as unknown as ReturnType<typeof useSession>);

const failing = {
  channel: "slack",
  destination: "hooks.slack.com",
  last_success_at: "2026-03-01T09:00:00Z",
  last_failure_at: "2026-03-02T09:00:00Z",
  last_failure: { code: "timeout", tr: "zaman aşımı", en: "timed out" },
  failing: true,
};

beforeEach(() => {
  api.getDeliveryStatus.mockReset();
  as("owner");
});

describe("DeliveryStatusCard", () => {
  it("lists each destination by host with its last success, last failure and the reason in words", async () => {
    api.getDeliveryStatus.mockResolvedValue([failing]);
    renderWithQuery(<DeliveryStatusCard />);
    expect(await screen.findByText("hooks.slack.com")).toBeInTheDocument();
    expect(screen.getByText("Şu an başarısız")).toBeInTheDocument();
    expect(screen.getByText(/Son başarılı gönderim:/)).toBeInTheDocument();
    expect(screen.getByText(/Son başarısız gönderim:.*Neden: zaman aşımı/)).toBeInTheDocument();
  });

  it("says plainly when a destination never succeeded or never failed", async () => {
    api.getDeliveryStatus.mockResolvedValue([
      { ...failing, channel: "webhook", destination: "example.com", last_success_at: null, last_failure_at: null, last_failure: null, failing: false },
    ]);
    renderWithQuery(<DeliveryStatusCard />);
    expect(await screen.findByText("example.com")).toBeInTheDocument();
    expect(screen.getByText("Başarılı gönderim yok")).toBeInTheDocument();
    expect(screen.getByText("Başarısız gönderim yok")).toBeInTheDocument();
    expect(screen.queryByText("Şu an başarısız")).toBeNull();
  });

  it("shows a visible fallback when the server has no words for the reason", async () => {
    api.getDeliveryStatus.mockResolvedValue([{ ...failing, last_failure: { code: "failed" } }]);
    renderWithQuery(<DeliveryStatusCard />);
    expect(await screen.findByText(/Neden: neden bildirilmedi/)).toBeInTheDocument();
  });

  it("says so when nothing was sent yet, and when the status could not be read", async () => {
    api.getDeliveryStatus.mockResolvedValueOnce([]);
    const first = renderWithQuery(<DeliveryStatusCard />);
    expect(await screen.findByText("Henüz bir bildirim hedefine gönderim denenmedi.")).toBeInTheDocument();
    first.unmount();
    api.getDeliveryStatus.mockRejectedValueOnce(Object.assign(new Error("x"), { status: 500 }));
    renderWithQuery(<DeliveryStatusCard />);
    expect(await screen.findByText("Gönderim durumu verisi alınamadı.")).toBeInTheDocument();
  });

  it("names who may see it when the server answers 403", async () => {
    api.getDeliveryStatus.mockRejectedValue(Object.assign(new Error("Sadece admin ve owner erişebilir"), { status: 403 }));
    renderWithQuery(<DeliveryStatusCard />);
    expect(await screen.findByText(/yalnızca şirketin sahibi ve yöneticileri görebilir/)).toBeInTheDocument();
  });

  it("is not drawn, and asks nothing, for a role that may not read it", () => {
    as("cfo");
    renderWithQuery(<DeliveryStatusCard />);
    expect(screen.queryByText("Bildirim hedeflerinin son durumu")).toBeNull();
    expect(api.getDeliveryStatus).not.toHaveBeenCalled();
  });

  it("is drawn for an admin", async () => {
    as("admin");
    api.getDeliveryStatus.mockResolvedValue([failing]);
    renderWithQuery(<DeliveryStatusCard />);
    expect(await screen.findByText("hooks.slack.com")).toBeInTheDocument();
  });
});

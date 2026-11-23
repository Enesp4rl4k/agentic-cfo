import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PrivacyPanel } from "@/components/privacy/PrivacyPanel";
import type { PrivacyOverview } from "@/components/privacy/types";
import { en } from "@/lib/i18n/messages/en";
import { tr } from "@/lib/i18n/messages/tr";

const { client } = vi.hoisted(() => ({ client: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@/lib/api/client", () => ({ apiClient: client }));
vi.mock("@/hooks/useI18n", () => ({ useI18n: () => ({ locale: "tr", t: tr }) }));

const notice = (version: string, must: boolean) => ({
  version, url: null, accepted_version: must ? null : version, accepted_at: must ? null : "2026-11-01T10:00:00Z", must_accept: must,
});

function overview(over: Partial<PrivacyOverview> = {}): PrivacyOverview {
  return {
    role: "owner",
    third_parties: [{
      key: "llm_provider", name: "LLM sağlayıcısı", sends: "karşı taraf adları", masked: false, switch: "anahtar yok",
      reaches_from: ["transactions", "uploads"],
    }],
    notices: { privacy_notice: notice("taslak-1", true), terms: notice("taslak-1", false), must_accept: true },
    cooling_off_days: 7,
    retention: {
      platform: { upload_days: 0, outbox_body_days: 90, notification_days: 180, alert_history_days: 365, token_days: 30, audit_ip_days: 365 },
      effective: { upload_days: 0, outbox_body_days: 90, notification_days: 180, alert_history_days: 365, token_days: 30, audit_ip_days: 365 },
      company_choice: {}, floor_days: 30,
      company_keys: ["upload_days", "outbox_body_days", "notification_days", "alert_history_days"],
      dry_run: true, can_edit: true,
    },
    export: null,
    ...over,
  };
}

function serve(data: PrivacyOverview) {
  client.get.mockImplementation(async (path: string) => {
    if (path === "/privacy/overview") return { data: { data } };
    if (path === "/privacy/erasure-requests") return { data: { data: { requests: [] } } };
    throw new Error(`unexpected GET ${path}`);
  });
}

afterEach(() => vi.clearAllMocks());

describe("Veri ve gizlilik", () => {
  it("shows the third parties and says plainly when data is not masked", async () => {
    serve(overview());
    render(<PrivacyPanel />);
    expect(await screen.findByText("Veri ve gizlilik")).toBeTruthy();
    expect(screen.getByText("LLM sağlayıcısı")).toBeTruthy();
    expect(screen.getByText(tr.settingsPrivacy.thirdParties.notMasked)).toBeTruthy();
    expect(screen.getByText(/transactions, uploads/)).toBeTruthy();
    expect(screen.getByText(tr.settingsPrivacy.retention.dryRunOn)).toBeTruthy();
  });

  it("records the acceptance of the current versions", async () => {
    serve(overview());
    client.post.mockResolvedValue({ data: { data: {} } });
    render(<PrivacyPanel />);
    fireEvent.click(await screen.findByText(tr.settingsPrivacy.notices.accept));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith("/privacy/notices/accept", { privacy_notice: "taslak-1" }));
  });

  it("asks the owner to type the e-mail address before the account deletion is requested", async () => {
    serve(overview({ notices: { privacy_notice: notice("v", false), terms: notice("v", false), must_accept: false } }));
    client.post.mockResolvedValue({ data: { data: { execute_after: "2026-12-01T00:00:00Z" } } });
    render(<PrivacyPanel />);
    const button = (await screen.findByText(tr.settingsPrivacy.mine.deleteButton)) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(tr.settingsPrivacy.mine.emailLabel), { target: { value: "ben@example.com" } });
    fireEvent.click(button);
    await waitFor(() => expect(client.post).toHaveBeenCalledWith("/privacy/member-erasure", { confirmation: "ben@example.com" }));
    expect(await screen.findByText(/Silme planlandı/)).toBeTruthy();
  });

  it("explains a sole owner's refusal", async () => {
    serve(overview());
    client.post.mockRejectedValue({ response: { data: { detail: "sole_owner: tek sahip" } } });
    render(<PrivacyPanel />);
    fireEvent.change(await screen.findByLabelText(tr.settingsPrivacy.mine.emailLabel), { target: { value: "ben@example.com" } });
    fireEvent.click(screen.getByText(tr.settingsPrivacy.mine.deleteButton));
    expect(await screen.findByText(tr.settingsPrivacy.mine.soleOwner)).toBeTruthy();
  });

  it("lets the owner ask for the company export, and tells everyone else it is the owner's", async () => {
    serve(overview());
    client.post.mockResolvedValue({ data: { data: { export_id: "e1", status: "queued", size_bytes: null, expires_at: null, download: null, error_code: null } } });
    const { unmount } = render(<PrivacyPanel />);
    fireEvent.click(await screen.findByText(tr.settingsPrivacy.company.exportRequest));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith("/privacy/exports"));
    expect(await screen.findByText(tr.settingsPrivacy.company.exportWorking)).toBeTruthy();
    unmount();

    serve(overview({ role: "analyst" }));
    render(<PrivacyPanel />);
    expect(await screen.findByText(tr.settingsPrivacy.company.ownerOnly)).toBeTruthy();
    expect(screen.queryByText(tr.settingsPrivacy.company.exportRequest)).toBeNull();
  });

  it("saves the company's retention choices as day numbers, empty meaning the default", async () => {
    serve(overview());
    client.put.mockResolvedValue({ data: { data: {} } });
    render(<PrivacyPanel />);
    fireEvent.change(await screen.findByLabelText(/Gönderilen e-posta gövdeleri.*Şirketinizin değeri/), { target: { value: "60" } });
    fireEvent.click(screen.getByText(tr.settingsPrivacy.retention.save));
    await waitFor(() => expect(client.put).toHaveBeenCalledWith("/privacy/retention", {
      policy: { upload_days: null, outbox_body_days: 60, notification_days: null, alert_history_days: null },
    }));
  });

  it("answers a failed load with a message, not a blank page", async () => {
    client.get.mockRejectedValue(new Error("down"));
    render(<PrivacyPanel />);
    expect(await screen.findByText(tr.settingsPrivacy.loadFailed)).toBeTruthy();
  });
});

describe("settingsPrivacy messages", () => {
  const keys = (o: unknown, prefix = ""): string[] =>
    Object.entries(o as Record<string, unknown>).flatMap(([k, v]) =>
      typeof v === "object" && v !== null ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`]);

  it("has the same keys in both languages, each a non-empty string", () => {
    expect(keys(tr.settingsPrivacy).sort()).toEqual(keys(en.settingsPrivacy).sort());
    for (const k of keys(en.settingsPrivacy)) expect(k.length).toBeGreaterThan(0);
  });

  it("keeps every placeholder the code fills in both languages", () => {
    for (const msgs of [tr, en]) {
      const p = msgs.settingsPrivacy;
      expect(p.mine.deleteIntro).toContain("{days}");
      expect(p.company.eraseIntro).toContain("{days}");
      expect(p.company.erasePhrase).toContain("{phrase}");
      expect(p.company.exportReady).toContain("{date}");
      expect(p.retention.floor).toContain("{n}");
      expect(p.notices.version).toContain("{v}");
    }
  });
});

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
    support_contact: null,
    retention: {
      platform: { upload_days: 0, outbox_body_days: 90, notification_days: 180, alert_history_days: 365, token_days: 30, audit_ip_days: 365 },
      effective: { upload_days: 0, outbox_body_days: 90, notification_days: 180, alert_history_days: 365, token_days: 30, audit_ip_days: 365 },
      company_choice: {}, floor_days: 30,
      company_keys: ["upload_days", "outbox_body_days", "notification_days", "alert_history_days"],
      dry_run: true, can_edit: true,
    },
    export: null,
    ai_egress: aiView(),
    ...over,
  };
}

function aiView(over: Partial<NonNullable<PrivacyOverview["ai_egress"]>> = {}): NonNullable<PrivacyOverview["ai_egress"]> {
  return {
    mode: "masked", source: "platform", platform_mode: "masked", organisation_choice: null, choice_capped: false,
    allowed_modes: ["off", "masked"], provider_host: "api.deepseek.com", provider_is_local: false, model: "deepseek-chat",
    document_text: "allow",
    categories: [
      { key: "figures", state: "sent" }, { key: "counterparties", state: "replaced" }, { key: "company", state: "replaced" },
      { key: "identifiers", state: "replaced" }, { key: "descriptions", state: "partly" }, { key: "document_text", state: "partly" },
      { key: "chat", state: "partly" }, { key: "embeddings", state: "partly" },
    ],
    usage: { days: 30, calls: 1234, bytes_out: 5_242_880, calls_by_mode: { masked: 1234 } },
    dictionary: { known_names: 42, truncated: false, complete: true },
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

  it("shows the owner what leaves for the AI provider: host, model, mode, categories, counters, residual risk", async () => {
    serve(overview());
    render(<PrivacyPanel />);
    const a = tr.settingsPrivacy.aiEgress;
    expect(await screen.findByText(a.title)).toBeTruthy();
    expect(screen.getByText(/api\.deepseek\.com · deepseek-chat/)).toBeTruthy();
    expect(screen.getByText(a.outside)).toBeTruthy();
    expect((screen.getByLabelText(new RegExp(a.modes.masked.label)) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(new RegExp(a.modes.raw.label)) as HTMLInputElement).disabled).toBe(true); // above the operator's ceiling
    expect(screen.getByText(a.categories.figures)).toBeTruthy();
    expect(screen.getAllByText(a.states.replaced).length).toBe(3);
    expect(screen.getByText("1.234 çağrı, 5 MB gönderildi.")).toBeTruthy();
    expect(screen.getByText(a.residual)).toBeTruthy();
    expect(screen.getByText(tr.settingsPrivacy.thirdParties.notMasked)).toBeTruthy(); // the LLM card of this fixture says masked:false
  });

  it("is absent for anyone but the owner", async () => {
    serve(overview({ role: "analyst", ai_egress: null }));
    render(<PrivacyPanel />);
    await screen.findByText("Veri ve gizlilik");
    expect(screen.queryByText(tr.settingsPrivacy.aiEgress.title)).toBeNull();
  });

  it("lets the owner tighten the mode and says when an earlier choice is capped", async () => {
    serve(overview({ ai_egress: aiView({ organisation_choice: "raw", choice_capped: true, source: "platform" }) }));
    client.put.mockResolvedValue({ data: { data: {} } });
    render(<PrivacyPanel />);
    const a = tr.settingsPrivacy.aiEgress;
    expect(await screen.findByText(a.capped)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(new RegExp(a.modes.off.label)));
    await waitFor(() => expect(client.put).toHaveBeenCalledWith("/privacy/ai-data-mode", { mode: "off" }));
    fireEvent.click(screen.getByText(a.useDefault));
    await waitFor(() => expect(client.put).toHaveBeenCalledWith("/privacy/ai-data-mode", { mode: null }));
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

  describe("erasure request state, owner only", () => {
    const row = (status: string, over: Record<string, unknown> = {}) => ({
      request_id: "abcdef12-0000-4000-8000-000000000000", scope: "org", status, execute_after: null, about_me: false,
      cancellable: false, failure_code: null, blocked_reason: null, ...over,
    });
    const serveRows = (data: PrivacyOverview, rows: unknown[]) =>
      client.get.mockImplementation(async (path: string) => {
        if (path === "/privacy/overview") return { data: { data } };
        if (path === "/privacy/erasure-requests") return { data: { data: { requests: rows } } };
        throw new Error(`unexpected GET ${path}`);
      });
    const s = tr.settingsPrivacy.company.states;

    it("says a scheduled erasure is scheduled, with its date, and offers the cancel", async () => {
      serveRows(overview(), [row("scheduled", { execute_after: "2026-12-01T00:00:00Z", cancellable: true })]);
      render(<PrivacyPanel />);
      expect(await screen.findByText(/Planlandı: silme .* tarihinde yapılacak/)).toBeTruthy();
      expect(screen.getByText(tr.settingsPrivacy.company.eraseCancel)).toBeTruthy();
      expect(screen.getByText("Referans: abcdef12")).toBeTruthy();
    });

    it("says a running erasure and one in cleanup cannot be cancelled", async () => {
      serveRows(overview(), [row("executing"), row("cleanup_pending", { request_id: "99999999-0000-4000-8000-000000000000", failure_code: "cleanup_failed" })]);
      render(<PrivacyPanel />);
      expect(await screen.findByText(s.executing)).toBeTruthy();
      expect(screen.getByText(s.cleanupPending)).toBeTruthy();
      expect(screen.queryByText(tr.settingsPrivacy.company.eraseCancel)).toBeNull();
      expect(screen.queryByText(/cleanup_failed/)).toBeNull(); // the internal code is never shown
    });

    it("tells the owner to contact support when it failed, with the configured contact", async () => {
      serveRows(overview({ support_contact: "destek@example.test" }), [row("failed", { failure_code: "erase_failed", cancellable: true })]);
      render(<PrivacyPanel />);
      expect(await screen.findByText(s.failed)).toBeTruthy();
      expect(screen.getByText("Destek: destek@example.test")).toBeTruthy();
      expect(screen.queryByText(/erase_failed/)).toBeNull();
    });

    it("falls back to the platform administrator when no support contact is configured, also when blocked", async () => {
      serveRows(overview(), [row("blocked", { blocked_reason: "retries_exhausted" })]);
      render(<PrivacyPanel />);
      expect(await screen.findByText(s.blocked)).toBeTruthy();
      expect(screen.getByText(s.contactNone)).toBeTruthy();
      expect(screen.queryByText(/retries_exhausted/)).toBeNull();
    });

    it("shows nothing of it to a member who is not the owner", async () => {
      serveRows(overview({ role: "analyst" }), [row("failed")]);
      render(<PrivacyPanel />);
      expect(await screen.findByText(tr.settingsPrivacy.company.ownerOnly)).toBeTruthy();
      expect(screen.queryByText(s.failed)).toBeNull();
    });
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

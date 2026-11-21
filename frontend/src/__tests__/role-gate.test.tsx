/**
 * Controls whose route the backend guards by role: a role that may not do it sees the control
 * disabled with the reason (not a dead button that answers 403), an allowed role sees it enabled,
 * and a 403 that still happens is said in words. One table for the components, one primitive.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useSession } from "next-auth/react";
import { ledgerSpies, renderWithQuery } from "./dashboard-mocks";
import { ACTION_CLASS, canClosePeriod, hasRoleClass, ROLE_CLASSES, type GatedAction } from "@/lib/roles";
import { failureMessage, isForbidden } from "@/lib/forbidden";
import { getMessages } from "@/lib/i18n";
import { useCan } from "@/hooks/useCan";

const { api, members } = vi.hoisted(() => ({
  api: {
    getPendingActions: vi.fn(), approveAction: vi.fn(), rejectAction: vi.fn(),
    rerunAnalysis: vi.fn(), listJobs: vi.fn(),
    getClosedPeriods: vi.fn(), closePeriod: vi.fn(), getOgrenilmisKurallar: vi.fn(), deleteOgrenilmisKural: vi.fn(),
    buildDefensibilityPacket: vi.fn(), finalizeDefensibilityPacket: vi.fn(), exportDefensibilityPacket: vi.fn(),
    parasutDurum: vi.fn(), parasutBaglan: vi.fn(), parasutFirmaSec: vi.fn(), syncParasut: vi.fn(),
    disconnectParasut: vi.fn(), parasutOtomatik: vi.fn(),
    listConnectors: vi.fn(), connectConnector: vi.fn(), syncConnector: vi.fn(),
    listDataSources: vi.fn(), uploadDataSource: vi.fn(), deleteDataSource: vi.fn(), analyzeCSuiteFromJob: vi.fn(),
    listDecisions: vi.fn(), measureOutcome: vi.fn(), createDecision: vi.fn(),
    getLedgerSummary: vi.fn(),
    clientGet: vi.fn(),
  },
  members: { list: [] as { role: string }[] },
}));

vi.mock("@/lib/api/actions", () => api);
vi.mock("@/lib/api/cfo", () => ({ rerunAnalysis: api.rerunAnalysis, listJobs: api.listJobs }));
vi.mock("@/lib/api/smmm", () => api);
vi.mock("@/lib/api/erp", () => api);
vi.mock("@/lib/api/connectors", () => api);
vi.mock("@/lib/api/datasource", async () => ({ ...(await vi.importActual<object>("@/lib/api/datasource")), ...api }));
vi.mock("@/lib/api/decisions", () => api);
vi.mock("@/lib/api/ledger", async () => ({ ...(await import("./dashboard-mocks")).ledgerModule, getLedgerSummary: api.getLedgerSummary }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: (...a: unknown[]) => api.clientGet(...a) } }));
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/x",
  useRouter: () => ({ push: vi.fn() }),
}));

import { ActionCenter } from "@/components/ActionCenter";
import { LedgerCard } from "@/components/command-center/LedgerCard";
import { RuleRerunBanner } from "@/components/transactions/RuleFeedback";
import { DefensibilityPacketCard } from "@/components/smmm/DefensibilityPacketCard";
import { DonemKilitleri } from "@/components/smmm/DonemKilitleri";
import { OgrenilmisKurallar } from "@/components/smmm/OgrenilmisKurallar";
import { ParasutKarti } from "@/components/integrations/ParasutKarti";
import { GitHubConnectorCard } from "@/components/cto/GitHubConnectorCard";
import { DomainDataSources } from "@/components/ceo/DomainDataSources";
import { DecisionLogPanel } from "@/components/ui/decision-log-panel";
import { MultiBatchUpload } from "@/components/upload/MultiBatchUpload";

const tr = getMessages("tr");
const gate = tr.roleGate;

function actAs(role: string | null) {
  vi.mocked(useSession).mockReturnValue({
    data: role ? { user: { id: "u1", email: "a@b.c", role, orgId: "org1" }, accessToken: "tok" } : null,
    status: role ? "authenticated" : "unauthenticated",
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  members.list = [];
  api.clientGet.mockImplementation(async () => ({ data: { data: { members: members.list } } }));
});

// ── the primitive ───────────────────────────────────────────────────────────

function Probe({ action }: { action: GatedAction }) {
  const can = useCan(action);
  return <p data-testid="p">{`${can.allowed}|${can.reason ?? ""}|${can.note ?? ""}`}</p>;
}
const probe = async (role: string | null, action: GatedAction) => {
  cleanup();
  actAs(role);
  renderWithQuery(<Probe action={action} />);
  return screen.getByTestId("p").textContent!.split("|");
};

describe("lib/roles: what a control may ask", () => {
  it("maps each action to the backend class that guards it", () => {
    expect(ACTION_CLASS).toEqual({ upload: "contributor", analyze: "contributor", edit: "writer", decide: "decider" });
    expect(hasRoleClass("analyst", ACTION_CLASS.upload)).toBe(true);
    expect(hasRoleClass("analyst", ACTION_CLASS.edit)).toBe(false);
    expect(ROLE_CLASSES.decider).not.toContain("cfo");
  });

  it("month close is the accountant's, or the owner's, admin's and cfo's when there is none", () => {
    expect(canClosePeriod("smmm", true)).toEqual({ allowed: true, case: "accountant" });
    expect(canClosePeriod("cfo", false)).toEqual({ allowed: true, case: "ownBooks" });
    expect(canClosePeriod("owner", null).allowed).toBe(true); // unknown yet: the server answers
    expect(canClosePeriod("admin", true)).toEqual({ allowed: false, case: "accountantExists" });
    expect(canClosePeriod("analyst", false)).toEqual({ allowed: false, case: "noRole" });
    expect(canClosePeriod(undefined, false).allowed).toBe(false);
  });
});

describe("useCan", () => {
  it.each([
    ["viewer", { upload: false, analyze: false, edit: false, decide: false }],
    ["analyst", { upload: true, analyze: true, edit: false, decide: false }],
    ["cfo", { upload: true, analyze: true, edit: true, decide: false }],
    ["smmm", { upload: true, analyze: true, edit: true, decide: false }],
    ["admin", { upload: true, analyze: true, edit: true, decide: true }],
    ["owner", { upload: true, analyze: true, edit: true, decide: true }],
    [null, { upload: false, analyze: false, edit: false, decide: false }],
  ] as const)("%s", async (role, expected) => {
    for (const action of Object.keys(expected) as (keyof typeof expected)[]) {
      const [allowed, reason] = await probe(role, action);
      expect(allowed === "true", `${role} ${action}`).toBe(expected[action]);
      expect(reason !== "").toBe(!expected[action]);
    }
  });

  it("explains which month-close case applies", async () => {
    expect(await probe("smmm", "closePeriod")).toEqual(["true", "", gate.closePeriod.accountant]);
    members.list = [];
    expect(await probe("cfo", "closePeriod")).toEqual(["true", "", gate.closePeriod.ownBooks]);
    members.list = [{ role: "smmm" }];
    cleanup();
    actAs("cfo");
    renderWithQuery(<Probe action="closePeriod" />);
    await waitFor(() =>
      expect(screen.getByTestId("p").textContent).toBe(`false|${gate.closePeriod.accountantExists}|`),
    );
    expect((await probe("viewer", "closePeriod"))[0]).toBe("false");
  });
});

describe("failureMessage", () => {
  it("shows the server's sentence for a 403, ours when it has none, and the caller's for anything else", () => {
    const refused = Object.assign(new Error("Bu işlem için yönetici gerekli."), { status: 403 });
    expect(isForbidden(refused)).toBe(true);
    expect(failureMessage(refused, "olmadı", gate.forbidden)).toBe("Bu işlem için yönetici gerekli.");
    expect(failureMessage(Object.assign(new Error(""), { status: 403 }), "olmadı", gate.forbidden)).toBe(gate.forbidden);
    expect(failureMessage(Object.assign(new Error("boom"), { status: 500 }), "olmadı", gate.forbidden)).toBe("olmadı");
    expect(isForbidden(null)).toBe(false);
  });
});

// ── the components: viewer sees it disabled with the reason, an allowed role sees it enabled ──

const kural = { id: "k1", anahtar: "KIRA", hesap_kodu: "770", hesap_adi: "Kira", onay_sayisi: 2, aktif: true };
const decisionRec = {
  id: "dec-1", job_id: "j1", org_id: "o1", topic: "Konu", chosen_option_id: "a", chosen_option_label: "A",
  rationale: null, expected: {}, status: "open", actual: null, variance: null, outcome_note: null,
  measured_at: null, created_by: "u", created_at: "2026-09-20T10:00:00+00:00", updated_at: "2026-09-20T10:00:00+00:00",
};

type Case = {
  name: string;
  allowed: string;
  blocked: string;
  reason: string;
  setup?: () => void;
  ui: () => React.ReactElement;
  control: () => Promise<HTMLElement>;
  ready?: () => void;
};

const byName = (name: string | RegExp) => () => screen.findByRole("button", { name });
const cases: Case[] = [
  {
    name: "ActionCenter approve", allowed: "admin", blocked: "viewer", reason: gate.needDecide,
    setup: () => api.getPendingActions.mockResolvedValue([{ id: "a1", debate_id: "d", description: "EFT", responsible_agent: "cfo", status: "pending", created_at: "" }]),
    ui: () => <ActionCenter />, control: () => screen.findByText("Onayla").then((e) => e.closest("button")!),
  },
  {
    name: "LedgerCard duplicate", allowed: "cfo", blocked: "analyst", reason: gate.needWrite,
    setup: () => {
      api.getLedgerSummary.mockResolvedValue(null);
      ledgerSpies.getProposedSettlements.mockResolvedValue([]);
      ledgerSpies.getPossibleDuplicates.mockResolvedValue([
        { id: "r1", transaction_date: "2026-11-12", amount_cents: 1000, description: "Kira", matches: [] },
      ]);
    },
    ui: () => <LedgerCard />, control: byName(tr.ledger.keep),
  },
  {
    name: "RuleRerunBanner", allowed: "analyst", blocked: "viewer", reason: gate.needContribute,
    ui: () => <RuleRerunBanner jobIds={["j1"]} onDismiss={() => {}} />, control: byName(tr.ruleFeedback.rerun),
  },
  {
    name: "DefensibilityPacketCard build", allowed: "smmm", blocked: "viewer", reason: gate.needWrite,
    ui: () => <DefensibilityPacketCard jobId="j1" />, control: byName("Paketi oluştur"),
  },
  {
    name: "DonemKilitleri close", allowed: "smmm", blocked: "viewer", reason: gate.closePeriod.noRole,
    setup: () => api.getClosedPeriods.mockResolvedValue([]),
    ui: () => <DonemKilitleri now={new Date(2026, 2, 15)} />, control: byName("Kapat"),
    ready: () => fireEvent.change(screen.getByLabelText("Dönemi kapat"), { target: { value: "2026-02" } }),
  },
  {
    name: "OgrenilmisKurallar remove", allowed: "smmm", blocked: "analyst", reason: gate.accountantAct.noRole,
    setup: () => api.getOgrenilmisKurallar.mockResolvedValue([kural]),
    ui: () => <OgrenilmisKurallar />, control: byName(/KIRA/),
  },
  {
    name: "ParasutKarti connect", allowed: "owner", blocked: "cfo", reason: gate.needDecide,
    setup: () => api.parasutDurum.mockResolvedValue({ acik: true, baglanti: null, firmalar: [] }),
    ui: () => <ParasutKarti />, control: byName("Paraşüt ile bağlan"),
  },
  {
    name: "GitHubConnectorCard sync", allowed: "cfo", blocked: "viewer", reason: gate.needWrite,
    setup: () => api.listConnectors.mockResolvedValue([{ name: "github", connected: true, last_sync_at: null, last_record_count: null, last_error: null }]),
    ui: () => <GitHubConnectorCard />, control: byName(/senkronize et/),
  },
  {
    name: "DomainDataSources upload", allowed: "analyst", blocked: "viewer", reason: gate.needContribute,
    setup: () => {
      api.listJobs.mockResolvedValue([{ job_id: "j1", status: "completed" }]);
      api.listDataSources.mockResolvedValue({ by_domain: {} });
    },
    ui: () => <DomainDataSources />, control: async () => (await screen.findAllByRole("button", { name: /\S/ }))[0],
    ready: () => {},
  },
  {
    name: "DecisionLogPanel measure", allowed: "cfo", blocked: "analyst", reason: gate.needWrite,
    setup: () => api.listDecisions.mockResolvedValue([decisionRec]),
    ui: () => <DecisionLogPanel />, control: byName("Sonucu ölç"),
  },
];

describe.each(cases)("$name", (c) => {
  it(`shows ${c.blocked} the control disabled, with the reason`, async () => {
    c.setup?.();
    actAs(c.blocked);
    renderWithQuery(c.ui());
    const button = await c.control();
    c.ready?.();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("title", c.reason);
  });

  it(`shows ${c.allowed} the control enabled`, async () => {
    c.setup?.();
    actAs(c.allowed);
    renderWithQuery(c.ui());
    const button = await c.control();
    c.ready?.();
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(button).not.toHaveAttribute("aria-disabled");
  });
});

describe("a blocked control does nothing", () => {
  it("does not call the server when a viewer clicks the approve button", async () => {
    api.getPendingActions.mockResolvedValue([{ id: "a1", debate_id: "d", description: "EFT", responsible_agent: "cfo", status: "pending", created_at: "" }]);
    actAs("viewer");
    renderWithQuery(<ActionCenter />);
    fireEvent.click(await screen.findByText("Onayla"));
    expect(api.approveAction).not.toHaveBeenCalled();
  });
});

describe("the month-close case, said on the card", () => {
  it("tells the owner of a company without an accountant that closing is theirs", async () => {
    api.getClosedPeriods.mockResolvedValue([]);
    actAs("owner");
    renderWithQuery(<DonemKilitleri now={new Date(2026, 2, 15)} />);
    expect(await screen.findByText(gate.closePeriod.ownBooks)).toBeInTheDocument();
  });

  it("tells the cfo of a company with an accountant that the accountant closes", async () => {
    api.getClosedPeriods.mockResolvedValue([]);
    members.list = [{ role: "smmm" }];
    actAs("cfo");
    renderWithQuery(<DonemKilitleri now={new Date(2026, 2, 15)} />);
    const close = await screen.findByRole("button", { name: "Kapat" });
    await waitFor(() => expect(close).toHaveAttribute("title", gate.closePeriod.accountantExists));
    expect(close).toHaveAttribute("aria-disabled", "true");
  });
});

describe("a 403 that still happens", () => {
  const refusal = Object.assign(new Error("Bu işlem için yönetici gerekli; rolünüz yapamaz."), { status: 403 });

  it("ActionCenter says it on the page instead of an alert()", async () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    api.getPendingActions.mockResolvedValue([{ id: "a1", debate_id: "d", description: "EFT", responsible_agent: "cfo", status: "pending", created_at: "" }]);
    api.approveAction.mockRejectedValue(refusal);
    actAs("admin"); // a stale role in the browser: the server still refuses
    renderWithQuery(<ActionCenter />);
    fireEvent.click(await screen.findByText("Onayla"));
    expect(await screen.findByRole("status")).toHaveTextContent(refusal.message);
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("LedgerCard says it as an alert", async () => {
    api.getLedgerSummary.mockResolvedValue(null);
    ledgerSpies.getProposedSettlements.mockResolvedValue([]);
    ledgerSpies.getPossibleDuplicates.mockResolvedValue([{ id: "r1", transaction_date: "2026-11-12", amount_cents: 1000, description: "Kira", matches: [] }]);
    ledgerSpies.resolveDuplicate.mockRejectedValue(refusal);
    actAs("cfo");
    renderWithQuery(<LedgerCard />);
    fireEvent.click(await screen.findByRole("button", { name: tr.ledger.keep }));
    expect(await screen.findByRole("alert")).toHaveTextContent(refusal.message);
  });

  it("the rerun banner says it when a rerun is refused", async () => {
    api.rerunAnalysis.mockRejectedValue(refusal);
    actAs("analyst");
    renderWithQuery(<RuleRerunBanner jobIds={["j1"]} onDismiss={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: tr.ruleFeedback.rerun }));
    expect(await screen.findByRole("alert")).toHaveTextContent(refusal.message);
  });

  it("the GitHub card says it when a sync is refused", async () => {
    api.listConnectors.mockResolvedValue([{ name: "github", connected: true, last_sync_at: null, last_record_count: null, last_error: null }]);
    api.syncConnector.mockRejectedValue(refusal);
    actAs("cfo");
    renderWithQuery(<GitHubConnectorCard />);
    fireEvent.click(await screen.findByRole("button", { name: /senkronize et/ }));
    expect(await screen.findByText(refusal.message)).toBeInTheDocument();
  });
});

describe("upload drop zone", () => {
  it("is closed to a viewer, with the reason, and open to an analyst", () => {
    actAs("viewer");
    const { unmount } = renderWithQuery(<MultiBatchUpload />);
    expect(screen.getByLabelText("Dosya seç")).toBeDisabled();
    expect(screen.getByRole("region", { name: "Dosya yükleme alanı" })).toHaveAttribute("title", gate.needContribute);
    unmount();
    actAs("analyst");
    renderWithQuery(<MultiBatchUpload />);
    expect(screen.getByLabelText("Dosya seç")).not.toBeDisabled();
  });
});

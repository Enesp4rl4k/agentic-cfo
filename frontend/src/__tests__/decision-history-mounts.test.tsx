/**
 * "Karar geçmişi" on the object pages, and the decision log in the menu.
 *
 * Read-only. The request names the object and no kind, so the server leaves out what the role may not read;
 * a 403 is said quietly. The history is closed until asked for, so a list does not ask the server once per row.
 * The company-wide log entry is drawn only for the roles that may read it (owner, admin, cfo, smmm).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

const { list, get } = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/api/decisionRecords", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api/decisionRecords")>("@/lib/api/decisionRecords")),
  listDecisionEntries: (...a: unknown[]) => list(...a),
}));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: (...a: unknown[]) => get(...a) } }));
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import { DecisionHistory } from "@/components/decisions/DecisionHistory";
import { DecisionHistoryToggle } from "@/components/decisions/DecisionHistoryToggle";
import { pairTargetId } from "@/lib/decisionTargets";
import { NAV_GROUPS } from "@/lib/nav-items";
import { FOCUS_HREFS, hiddenNavItems, visibleNavGroups } from "@/lib/nav-focus";
import { renderWithQuery } from "./dashboard-mocks";

const entry = {
  id: "d1", kind: "plan_change", target_type: "payment_plan_change", target_id: "c1", outcome: "approved",
  decided_by: "u1", decided_via: "human", rule_id: null, decided_at: "2026-03-01T10:00:00Z", reason: null,
  evidence_refs: [], before: null, after: null, supersedes_id: null, superseded_by_id: null,
};
const forbidden = () => Object.assign(new Error("Bu türdeki karar kayıtlarını görme yetkiniz yok."), { status: 403 });

beforeEach(() => {
  list.mockReset();
  get.mockReset();
  get.mockResolvedValue({ data: { data: { members: [{ user_id: "u1", full_name: "Ayşe Yılmaz", email: "a@x.com" }] } } });
});

describe("DecisionHistory", () => {
  it("asks for one object and names no kind, and shows who decided", async () => {
    list.mockResolvedValue({ entries: [entry], total: 1 });
    renderWithQuery(<DecisionHistory targetType="payment_plan_change" targetId="c1" />);
    expect(await screen.findByText("Ayşe Yılmaz")).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith({ targetType: "payment_plan_change", targetId: "c1", kind: undefined });
  });

  it("narrows to one kind only when the screen asks for it", async () => {
    list.mockResolvedValue({ entries: [], total: 0 });
    renderWithQuery(<DecisionHistory targetType="organization" targetId="o1" kind="base_currency_confirmation" />);
    expect(await screen.findByText("Bu kayıt için karar kaydı yok.")).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith({ targetType: "organization", targetId: "o1", kind: "base_currency_confirmation" });
  });

  it("says quietly that the records are not for this role (403), without an alert", async () => {
    list.mockRejectedValue(forbidden());
    renderWithQuery(<DecisionHistory targetType="payment_plan_change" targetId="c1" />);
    expect(await screen.findByText("Bu kayıtları görme yetkiniz yok.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Karar geçmişi okunamadı.")).toBeNull();
  });

  it("says it could not read the history on any other failure", async () => {
    list.mockRejectedValue(Object.assign(new Error("x"), { status: 500 }));
    renderWithQuery(<DecisionHistory targetType="payment_plan_change" targetId="c1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Karar geçmişi okunamadı.");
  });
});

describe("DecisionHistoryToggle", () => {
  it("asks nothing until it is opened, then reads the one object, and closes again", async () => {
    list.mockResolvedValue({ entries: [entry], total: 1 });
    renderWithQuery(<DecisionHistoryToggle targetType="payment_plan_change" targetId="c1" />);
    const button = screen.getByRole("button", { name: "Karar geçmişi" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(list).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Ayşe Yılmaz")).toBeInTheDocument();
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Ayşe Yılmaz")).toBeNull();
  });
});

describe("the account question's object id", () => {
  it("is the one the server records: sorted ids, groups sorted, first id of each", () => {
    expect(pairTargetId({ job_ids_a: ["b2", "a1"], job_ids_b: ["c3"] })).toBe("a1|c3");
    expect(pairTargetId({ job_ids_a: ["c3"], job_ids_b: ["b2", "a1"] })).toBe("a1|c3");
    expect(pairTargetId({ job_ids_a: ["z9", "a1"], job_ids_b: ["b2"] })).toBe("a1|b2");
  });
});

describe("the decision log in the menu", () => {
  const hrefs = (groups: { items: { href: string }[] }[]) => groups.flatMap((g) => g.items.map((i) => i.href));
  const menu = (role: string | null | undefined, focusMode: boolean) =>
    visibleNavGroups(NAV_GROUPS, { hasTrPack: true, focusMode, role });

  it.each(["owner", "admin", "cfo", "smmm"])("is offered to %s, also while focus mode keeps only the pilot flow", (role) => {
    expect(hrefs(menu(role, false))).toContain("/kararlar");
    expect(hrefs(menu(role, true))).toContain("/kararlar");
  });

  it.each(["analyst", "viewer", "nonsense", null, undefined])("is hidden from %s, in the menu and under Daha fazla", (role) => {
    expect(hrefs(menu(role, false))).not.toContain("/kararlar");
    expect(hrefs(menu(role, true))).not.toContain("/kararlar");
    const more = hiddenNavItems(NAV_GROUPS, { hasTrPack: true, focusMode: true, role }).map((i) => i.href);
    expect(more).not.toContain("/kararlar");
  });

  it("is part of the pilot flow in focus mode", () => {
    expect(FOCUS_HREFS.has("/kararlar")).toBe(true);
  });
});

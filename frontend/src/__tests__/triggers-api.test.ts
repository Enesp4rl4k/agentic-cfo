/**
 * P4-4 — Tetikleyici Motoru API modülü.
 *
 * The module's whole job is unwrapping the { data, error } envelope the backend
 * returns: data resolves, error throws with the server's message. That contract
 * is what every call site in the /tetikler page relies on, so it's pinned here
 * with a mocked axios client rather than on the page.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const { client } = vi.hoisted(() => ({
  client: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/lib/api/client", () => ({ apiClient: client }));

import {
  createTrigger, deleteTrigger, dryRunCondition, fetchTriggerMeta,
  listTriggerRuns, listTriggers, updateTrigger,
} from "@/lib/api/triggers";

const RULE = {
  id: "trg1", org_id: "org1", name: "Runway alarm", events: ["job.completed"],
  condition: { metric: "finance.runway_months", op: "lt", value: 3 },
  action_kind: "alert.dispatch", action_params: { severity: "critical" },
  cooldown_minutes: 30, enabled: true, created_at: null, updated_at: null,
};

beforeEach(() => vi.clearAllMocks());

describe("listTriggers", () => {
  it("unwraps the envelope into a rules array", async () => {
    client.get.mockResolvedValue({ data: { data: { triggers: [RULE] }, error: null } });
    const rules = await listTriggers();
    expect(rules).toHaveLength(1);
    expect(rules[0].name).toBe("Runway alarm");
    expect(client.get).toHaveBeenCalledWith("/tetikler");
  });

  it("defaults to an empty list when data is null", async () => {
    client.get.mockResolvedValue({ data: { data: null, error: null } });
    expect(await listTriggers()).toEqual([]);
  });

  it("throws the server error message when the envelope carries one", async () => {
    client.get.mockResolvedValue({ data: { data: null, error: "Yetkiniz yok." } });
    await expect(listTriggers()).rejects.toThrow("Yetkiniz yok.");
  });
});

describe("createTrigger", () => {
  it("posts the input and returns the created rule", async () => {
    client.post.mockResolvedValue({ data: { data: RULE, error: null } });
    const input = {
      name: "Runway alarm", events: ["job.completed"],
      condition: RULE.condition, action_kind: "alert.dispatch",
    };
    const created = await createTrigger(input);
    expect(created.id).toBe("trg1");
    expect(client.post).toHaveBeenCalledWith("/tetikler", input);
  });

  it("surfaces a validation error from the backend", async () => {
    client.post.mockResolvedValue({
      data: { data: null, error: "Bilinmeyen aksiyon türü: email.explode" },
    });
    await expect(
      createTrigger({ name: "x", events: ["schedule"], condition: {}, action_kind: "email.explode" })
    ).rejects.toThrow("Bilinmeyen aksiyon türü");
  });
});

describe("updateTrigger / deleteTrigger", () => {
  it("patches the given id and returns the merged rule", async () => {
    client.patch.mockResolvedValue({
      data: { data: { ...RULE, enabled: false }, error: null },
    });
    const updated = await updateTrigger("trg1", { enabled: false });
    expect(updated.enabled).toBe(false);
    expect(client.patch).toHaveBeenCalledWith("/tetikler/trg1", { enabled: false });
  });

  it("resolves void on delete", async () => {
    client.delete.mockResolvedValue({ data: { data: { deleted: true }, error: null } });
    await expect(deleteTrigger("trg1")).resolves.toBeUndefined();
    expect(client.delete).toHaveBeenCalledWith("/tetikler/trg1");
  });

  it("throws when deleting another org's rule (404 message)", async () => {
    client.delete.mockResolvedValue({ data: { data: null, error: "Tetikleyici bulunamadı." } });
    await expect(deleteTrigger("foreign")).rejects.toThrow("Tetikleyici bulunamadı.");
  });
});

describe("listTriggerRuns", () => {
  it("passes trigger_id and limit as query params", async () => {
    client.get.mockResolvedValue({ data: { data: { runs: [] }, error: null } });
    await listTriggerRuns("trg1", 25);
    expect(client.get).toHaveBeenCalledWith("/tetikler/runs", {
      params: { trigger_id: "trg1", limit: 25 },
    });
  });
});

describe("fetchTriggerMeta", () => {
  it("returns catalogs and falls back to a safe default on null data", async () => {
    client.get.mockResolvedValue({ data: { data: null, error: null } });
    const meta = await fetchTriggerMeta();
    expect(meta.action_kinds).toEqual([]);
    expect(meta.cooldown_default_minutes).toBe(60);
  });
});

describe("dryRunCondition", () => {
  it("posts condition + values and returns the verdict", async () => {
    const condition = { metric: "finance.runway_months", op: "lt", value: 3 };
    client.post.mockResolvedValue({
      data: { data: { would_fire: true, unknown_metrics: [], condition }, error: null },
    });
    const result = await dryRunCondition(condition, { "finance.runway_months": 2.5 });
    expect(result.would_fire).toBe(true);
    expect(client.post).toHaveBeenCalledWith("/tetikler/dry-run", {
      condition, values: { "finance.runway_months": 2.5 },
    });
  });

  it("reports catalog-missing metrics so a dead rule is diagnosable", async () => {
    const condition = { metric: "olmayan.metrik", op: "gt", value: 1 };
    client.post.mockResolvedValue({
      data: { data: { would_fire: false, unknown_metrics: ["olmayan.metrik"], condition }, error: null },
    });
    const result = await dryRunCondition(condition, {});
    expect(result.unknown_metrics).toEqual(["olmayan.metrik"]);
  });
});

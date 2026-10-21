"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Plus, RefreshCw, Trash2, Pencil, Play, X, CheckCircle2, AlertTriangle,
  Filter, History,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";
import type { MessageTree } from "@/lib/i18n";
import {
  createTrigger, deleteTrigger, dryRunCondition, fetchTriggerMeta, listTriggerRuns,
  listTriggers, updateTrigger,
  type DryRunResult, type TriggerCondition, type TriggerMeta, type TriggerRule,
  type TriggerRun,
} from "@/lib/api/triggers";

// ── Sabitler ──────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  fired: "bg-emerald-500/15 text-emerald-400",
  cooldown: "bg-amber-500/15 text-amber-400",
  condition_false: "bg-muted text-muted-foreground",
  duplicate: "bg-violet-500/15 text-violet-400",
  error: "bg-red-500/15 text-red-400",
};

interface SimpleCondition { metric: string; op: string; value: string }

function isSimpleCondition(
  c: TriggerCondition
): c is { metric: string; op: string; value: number } {
  return typeof c.metric === "string" && typeof c.op === "string"
    && typeof c.value === "number" && !c.all && !c.any && !c.not;
}

type EventKindKey = keyof MessageTree["tetikler"]["eventKinds"];

const EVENT_KIND_KEYS: Record<string, EventKindKey> = {
  "job.completed": "jobCompleted",
  "tx.arrived": "txArrived",
  "anomaly.detected": "anomalyDetected",
  schedule: "schedule",
};

/** Label + hint for a wire event kind; an unknown kind shows as-is, never blank. */
function eventKindText(t: MessageTree, kind: string): { label: string; hint: string } {
  const key = EVENT_KIND_KEYS[kind];
  return key ? t.tetikler.eventKinds[key] : { label: kind, hint: kind };
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("tr-TR", {
      day: "2-digit", month: "2-digit", year: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function errorText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

function statusLabel(
  status: string,
  t: MessageTree
): string {
  switch (status) {
    case "fired": return t.tetikler.statusFired;
    case "cooldown": return t.tetikler.statusCooldown;
    case "condition_false": return t.tetikler.statusConditionFalse;
    case "duplicate": return t.tetikler.statusDuplicate;
    case "error": return t.tetikler.statusError;
    default: return status;
  }
}

/** `{name}` yer tutucusunu değiştirir — mesajlar şablonlu gelir. */
function fill(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    template
  );
}

// ── Sayfa ─────────────────────────────────────────────────────────────────────

export default function TetiklerPage() {
  const { t } = useI18n();
  const [meta, setMeta] = useState<TriggerMeta | null>(null);
  const [rules, setRules] = useState<TriggerRule[]>([]);
  const [runs, setRuns] = useState<TriggerRun[]>([]);
  const [runsFilter, setRunsFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Form durumu
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [events, setEvents] = useState<string[]>(["job.completed"]);
  const [simple, setSimple] = useState<SimpleCondition>({
    metric: "finance.runway_months", op: "lt", value: "3",
  });
  const [conditionJson, setConditionJson] = useState("");
  const [jsonMode, setJsonMode] = useState(false);
  const [actionKind, setActionKind] = useState("alert.dispatch");
  const [paramsJson, setParamsJson] = useState("{}");
  const [cooldown, setCooldown] = useState("60");
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);

  // Dry-run durumu
  const [dryCondition, setDryCondition] = useState("");
  const [dryValues, setDryValues] = useState('{"finance.runway_months": 2.5}');
  const [dryResult, setDryResult] = useState<DryRunResult | null>(null);
  const [dryBusy, setDryBusy] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [m, list] = await Promise.all([fetchTriggerMeta(), listTriggers()]);
      setMeta(m);
      setRules(list);
    } catch (e) {
      setError(errorText(e, t.tetikler.errGeneric));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const refreshRuns = useCallback(async (triggerId: string | null) => {
    try {
      setRuns(await listTriggerRuns(triggerId ?? undefined));
    } catch (e) {
      setError(errorText(e, t.tetikler.errGeneric));
    }
  }, [t]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { void refreshRuns(runsFilter); }, [runsFilter, refreshRuns]);

  function resetForm() {
    setEditingId(null);
    setName("");
    setEvents(["job.completed"]);
    setSimple({ metric: "finance.runway_months", op: "lt", value: "3" });
    setConditionJson("");
    setJsonMode(false);
    setActionKind("alert.dispatch");
    setParamsJson("{}");
    setCooldown("60");
    setEnabled(true);
  }

  function startEdit(rule: TriggerRule) {
    setEditingId(rule.id);
    setName(rule.name);
    setEvents(rule.events);
    if (isSimpleCondition(rule.condition)) {
      setJsonMode(false);
      setSimple({
        metric: rule.condition.metric, op: rule.condition.op,
        value: String(rule.condition.value),
      });
      setConditionJson("");
    } else {
      setJsonMode(true);
      setConditionJson(JSON.stringify(rule.condition, null, 2));
      setSimple({ metric: "finance.runway_months", op: "lt", value: "3" });
    }
    setActionKind(rule.action_kind);
    setParamsJson(JSON.stringify(rule.action_params ?? {}, null, 2));
    setCooldown(String(rule.cooldown_minutes));
    setEnabled(rule.enabled);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function buildCondition(): TriggerCondition {
    if (jsonMode) return JSON.parse(conditionJson || "{}") as TriggerCondition;
    return {
      metric: simple.metric,
      op: simple.op,
      value: Number(simple.value),
    };
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!name.trim()) { setError(t.tetikler.errNameRequired); return; }
    if (events.length === 0) { setError(t.tetikler.errEventsRequired); return; }
    let condition: TriggerCondition;
    try {
      condition = buildCondition();
    } catch {
      setError(t.tetikler.errConditionJson); return;
    }
    let actionParams: Record<string, unknown>;
    try {
      actionParams = JSON.parse(paramsJson || "{}") as Record<string, unknown>;
    } catch {
      setError(t.tetikler.errParamsJson); return;
    }
    setSaving(true);
    try {
      const input = {
        name: name.trim(),
        events,
        condition,
        action_kind: actionKind,
        action_params: actionParams,
        cooldown_minutes: Number(cooldown) || 0,
        enabled,
      };
      if (editingId) {
        await updateTrigger(editingId, input);
        setNotice(fill(t.tetikler.updated, { name: input.name }));
      } else {
        await createTrigger(input);
        setNotice(fill(t.tetikler.created, { name: input.name }));
      }
      resetForm();
      await refresh();
    } catch (err) {
      setError(errorText(err, t.tetikler.errGeneric));
    } finally {
      setSaving(false);
    }
  }

  async function toggleEnabled(rule: TriggerRule) {
    setError(null);
    try {
      await updateTrigger(rule.id, { enabled: !rule.enabled });
      await refresh();
    } catch (err) {
      setError(errorText(err, t.tetikler.errGeneric));
    }
  }

  async function remove(rule: TriggerRule) {
    if (!window.confirm(fill(t.tetikler.confirmDelete, { name: rule.name }))) return;
    setError(null);
    try {
      await deleteTrigger(rule.id);
      setNotice(fill(t.tetikler.deleted, { name: rule.name }));
      if (editingId === rule.id) resetForm();
      await refresh();
    } catch (err) {
      setError(errorText(err, t.tetikler.errGeneric));
    }
  }

  async function runDryTest() {
    setError(null);
    setDryResult(null);
    let condition: TriggerCondition;
    let values: Record<string, number>;
    try {
      condition = JSON.parse(dryCondition || "{}") as TriggerCondition;
    } catch {
      setError(t.tetikler.errConditionJson); return;
    }
    try {
      values = JSON.parse(dryValues || "{}") as Record<string, number>;
    } catch {
      setError(t.tetikler.errValuesJson); return;
    }
    setDryBusy(true);
    try {
      setDryResult(await dryRunCondition(condition, values));
    } catch (err) {
      setError(errorText(err, t.tetikler.errGeneric));
    } finally {
      setDryBusy(false);
    }
  }

  function loadIntoDryRun(rule: TriggerRule) {
    setDryCondition(JSON.stringify(rule.condition, null, 2));
    setDryResult(null);
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl p-4 sm:p-6 lg:p-8">
        <div className="animate-pulse space-y-3 text-sm text-muted-foreground">
          <div className="h-7 w-56 rounded-md bg-muted/40" />
          <div className="h-4 w-96 max-w-full rounded-md bg-muted/30" />
          <div className="h-64 rounded-xl bg-muted/20" />
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6 lg:p-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Filter className="h-6 w-6 text-emerald-400" />
            {t.tetikler.title}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t.tetikler.subtitle}
          </p>
        </div>
        <button
          onClick={() => { void refresh(); void refreshRuns(runsFilter); }}
          className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm hover:bg-muted/40"
        >
          <RefreshCw className="h-4 w-4" /> {t.tetikler.refresh}
        </button>
      </header>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="ml-auto"
            aria-label={t.tetikler.cancel}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{notice}</span>
          <button
            onClick={() => setNotice(null)}
            className="ml-auto"
            aria-label={t.tetikler.cancel}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ── Kural formu ── */}
        <section className="rounded-xl border border-border/50 bg-card p-5">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
            <Plus className="h-4 w-4 text-emerald-400" />
            {editingId ? t.tetikler.editRule : t.tetikler.newRule}
          </h2>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">
                {t.tetikler.formName}
              </label>
              <input
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t.tetikler.formNamePlaceholder}
              />
            </div>

            <div>
              <label className="mb-1.5 block text-xs text-muted-foreground">
                {t.tetikler.formEvents}
              </label>
              <div className="flex flex-wrap gap-2">
                {(meta?.event_kinds ?? ["job.completed"]).map((k) => (
                  <label
                    key={k}
                    title={eventKindText(t, k).hint}
                    className={cn(
                      "flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs",
                      events.includes(k)
                        ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                        : "border-border bg-background text-muted-foreground"
                    )}
                  >
                    <input
                      type="checkbox"
                      className="hidden"
                      checked={events.includes(k)}
                      onChange={() => setEvents((prev) =>
                        prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]
                      )}
                    />
                    {eventKindText(t, k).label}
                  </label>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <label className="text-xs text-muted-foreground">{t.tetikler.formCondition}</label>
                <button
                  type="button"
                  onClick={() => {
                    if (!jsonMode) setConditionJson(JSON.stringify(buildCondition(), null, 2));
                    setJsonMode((v) => !v);
                  }}
                  className="text-xs text-emerald-400 hover:underline"
                >
                  {jsonMode ? t.tetikler.simpleEditor : t.tetikler.jsonEditor}
                </button>
              </div>
              {jsonMode ? (
                <textarea
                  rows={5}
                  className="w-full rounded-md border border-border bg-background p-3 font-mono text-xs"
                  value={conditionJson}
                  onChange={(e) => setConditionJson(e.target.value)}
                  placeholder={t.tetikler.formConditionPlaceholder}
                />
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  <select
                    className="h-9 rounded-md border border-border bg-background px-2 text-xs"
                    value={simple.metric}
                    onChange={(e) => setSimple({ ...simple, metric: e.target.value })}
                  >
                    {(meta?.metrics ?? []).map((m) => (
                      <option key={m.id} value={m.id}>{m.label}</option>
                    ))}
                    {!meta?.metrics.length && <option value="finance.runway_months">Runway</option>}
                  </select>
                  <select
                    className="h-9 rounded-md border border-border bg-background px-2 text-xs"
                    value={simple.op}
                    onChange={(e) => setSimple({ ...simple, op: e.target.value })}
                  >
                    {(meta?.operators ?? ["lt"]).map((op) => (
                      <option key={op} value={op}>{op}</option>
                    ))}
                  </select>
                  <input
                    type="number"
                    className="h-9 rounded-md border border-border bg-background px-2 text-xs"
                    value={simple.value}
                    onChange={(e) => setSimple({ ...simple, value: e.target.value })}
                  />
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">{t.tetikler.formAction}</label>
                <select
                  className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm"
                  value={actionKind}
                  onChange={(e) => setActionKind(e.target.value)}
                >
                  {(meta?.action_kinds ?? ["alert.dispatch"]).map((k) => (
                    <option key={k} value={k}>{k}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">{t.tetikler.formCooldown}</label>
                <input
                  type="number"
                  min={0}
                  className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
                  value={cooldown}
                  onChange={(e) => setCooldown(e.target.value)}
                />
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted-foreground">{t.tetikler.formParams}</label>
              <textarea
                rows={3}
                className="w-full rounded-md border border-border bg-background p-3 font-mono text-xs"
                value={paramsJson}
                onChange={(e) => setParamsJson(e.target.value)}
                placeholder={t.tetikler.formParamsPlaceholder}
              />
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              {t.tetikler.formEnabled}
            </label>

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={saving}
                className="flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              >
                {saving ? t.tetikler.submitSaving : editingId ? t.tetikler.submitUpdate : t.tetikler.submitCreate}
              </button>
              {editingId && (
                <button
                  type="button"
                  onClick={resetForm}
                  className="rounded-md border border-border px-4 py-2 text-sm hover:bg-muted/40"
                >
                  {t.tetikler.cancel}
                </button>
              )}
            </div>
          </form>
        </section>

        {/* ── Dry-run test cihazı ── */}
        <section className="rounded-xl border border-border/50 bg-card p-5">
          <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <Play className="h-4 w-4 text-violet-400" />
            {t.tetikler.dryRunTitle}
          </h2>
          <p className="mb-4 text-xs text-muted-foreground">
            {t.tetikler.dryRunSubtitle}
          </p>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">{t.tetikler.dryRunCondition}</label>
              <textarea
                rows={5}
                className="w-full rounded-md border border-border bg-background p-3 font-mono text-xs"
                value={dryCondition}
                onChange={(e) => setDryCondition(e.target.value)}
                placeholder={t.tetikler.dryRunConditionPlaceholder}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">{t.tetikler.dryRunValues}</label>
              <textarea
                rows={3}
                className="w-full rounded-md border border-border bg-background p-3 font-mono text-xs"
                value={dryValues}
                onChange={(e) => setDryValues(e.target.value)}
              />
            </div>
            <button
              onClick={() => { void runDryTest(); }}
              disabled={dryBusy}
              className="flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
            >
              <Play className="h-4 w-4" />
              {dryBusy ? t.tetikler.dryRunBusy : t.tetikler.dryRunButton}
            </button>
            {dryResult && (
              <div className="space-y-2 rounded-lg border border-border/50 bg-background p-3 text-sm">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded px-2 py-0.5 text-xs font-medium",
                      dryResult.would_fire
                        ? "bg-emerald-500/15 text-emerald-400"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {dryResult.would_fire ? t.tetikler.dryRunYes : t.tetikler.dryRunNo}
                  </span>
                </div>
                {dryResult.unknown_metrics.length > 0 && (
                  <p className="text-xs text-amber-400">
                    {fill(t.tetikler.dryRunUnknownMetrics, {
                      list: dryResult.unknown_metrics.join(", "),
                    })}
                  </p>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* ── Kurallar tablosu ── */}
      <section className="rounded-xl border border-border/50 bg-card p-5">
        <h2 className="mb-3 text-sm font-semibold">
          {fill(t.tetikler.rulesHeading, { count: rules.length })}
        </h2>
        {rules.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {t.tetikler.rulesEmpty}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colName}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colEvents}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colAction}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colCooldown}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colEnabled}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colLog}</th>
                  <th className="py-2 pr-3" />
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} className="border-b border-border/30 last:border-0">
                    <td className="max-w-[200px] truncate py-2.5 pr-3" title={rule.name}>
                      {rule.name}
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {rule.events.map((ev) => (
                          <span key={ev} title={eventKindText(t, ev).hint} className="rounded bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                            {eventKindText(t, ev).label}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-2.5 pr-3 font-mono text-xs">{rule.action_kind}</td>
                    <td className="py-2.5 pr-3 text-xs text-muted-foreground">
                      {fill(t.tetikler.cooldownUnit, { count: rule.cooldown_minutes })}
                    </td>
                    <td className="py-2.5 pr-3">
                      <button
                        onClick={() => { void toggleEnabled(rule); }}
                        aria-label={rule.enabled ? t.tetikler.toggleEnable : t.tetikler.toggleDisable}
                        className={cn(
                          "relative h-5 w-9 rounded-full transition-colors",
                          rule.enabled ? "bg-emerald-500/60" : "bg-muted"
                        )}
                      >
                        <span
                          className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
                          style={{ left: rule.enabled ? "18px" : "2px" }}
                        />
                      </button>
                    </td>
                    <td className="py-2.5 pr-3">
                      <button
                        onClick={() => setRunsFilter(rule.id)}
                        className="flex items-center gap-1 text-xs text-emerald-400 hover:underline"
                      >
                        <History className="h-3.5 w-3.5" /> {t.tetikler.logAria}
                      </button>
                    </td>
                    <td className="py-2.5">
                      <div className="flex justify-end gap-1">
                        <button
                          onClick={() => { loadIntoDryRun(rule); }}
                          title={t.tetikler.dryRunLoadAria}
                          className="rounded p-1.5 text-muted-foreground hover:bg-muted/40 hover:text-violet-400"
                        >
                          <Play className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => startEdit(rule)}
                          title={t.tetikler.editAria}
                          className="rounded p-1.5 text-muted-foreground hover:bg-muted/40 hover:text-emerald-400"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => { void remove(rule); }}
                          title={t.tetikler.deleteAria}
                          className="rounded p-1.5 text-muted-foreground hover:bg-muted/40 hover:text-red-400"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Denetim defteri ── */}
      <section className="rounded-xl border border-border/50 bg-card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            {t.tetikler.logHeading}
            {runsFilter && (
              <span className="ml-2 font-normal text-muted-foreground">
                ({fill(t.tetikler.logFiltered, {
                  name: rules.find((r) => r.id === runsFilter)?.name ?? runsFilter,
                })})
              </span>
            )}
          </h2>
          {runsFilter && (
            <button
              onClick={() => setRunsFilter(null)}
              className="flex items-center gap-1 text-xs text-emerald-400 hover:underline"
            >
              <X className="h-3.5 w-3.5" /> {t.tetikler.logClearFilter}
            </button>
          )}
        </div>
        {runs.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t.tetikler.logEmpty}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colTime}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colRule}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colEvent}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colStatus}</th>
                  <th className="py-2 pr-3 font-medium">{t.tetikler.colDetail}</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-b border-border/30 last:border-0">
                    <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted-foreground">
                      {fmtTime(run.created_at)}
                    </td>
                    <td className="max-w-[160px] truncate py-2 pr-3" title={run.trigger_id}>
                      {rules.find((r) => r.id === run.trigger_id)?.name ?? run.trigger_id}
                    </td>
                    <td className="py-2 pr-3">
                      <span title={run.event_ref} className="rounded bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                        {eventKindText(t, run.event_kind).label}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className={cn(
                        "rounded px-2 py-0.5 text-[11px] font-medium",
                        STATUS_STYLES[run.status] ?? "bg-muted text-muted-foreground"
                      )}>
                        {statusLabel(run.status, t)}
                      </span>
                    </td>
                    <td className="max-w-[280px] truncate py-2 pr-3 font-mono text-[11px] text-muted-foreground"
                        title={run.action_result ?? ""}>
                      {run.action_result ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="text-xs text-muted-foreground">
        {meta
          ? fill(t.tetikler.catalogHint, {
              metrics: meta.metrics.length,
              scenarios: meta.cascade_triggers.length,
            })
          : null}
      </p>
    </main>
  );
}

import { apiClient } from "./client";

// Tetikleyici Motoru (P4-4) — /tetikler endpoint'leri için tipli sarmalayıcı.
// Her metod sunucunun { data, error } zarfını çözer; hata durumunda Error fırlatır.

interface Envelope<T> {
  data: T | null;
  error: string | null;
}

export interface TriggerCondition {
  metric?: string;
  op?: string;
  value?: number;
  all?: TriggerCondition[];
  any?: TriggerCondition[];
  not?: TriggerCondition;
}

export interface TriggerRule {
  id: string;
  org_id: string | null;
  name: string;
  events: string[];
  condition: TriggerCondition;
  action_kind: string;
  action_params: Record<string, unknown>;
  cooldown_minutes: number;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface TriggerRun {
  id: string;
  org_id: string | null;
  trigger_id: string;
  event_kind: string;
  event_ref: string;
  status: string;
  action_kind: string | null;
  action_result: string | null;
  created_at: string | null;
}

export interface TriggerMeta {
  action_kinds: string[];
  event_kinds: string[];
  operators: string[];
  metrics: { id: string; label: string; unit: string; owner_role: string }[];
  cascade_triggers: string[];
  cooldown_default_minutes: number;
}

export interface DryRunResult {
  would_fire: boolean;
  unknown_metrics: string[];
  condition: TriggerCondition;
}

export interface TriggerRuleInput {
  name: string;
  events: string[];
  condition: TriggerCondition;
  action_kind: string;
  action_params?: Record<string, unknown>;
  cooldown_minutes?: number;
  enabled?: boolean;
}

/** Zarfı çözer: hata varsa fırlatır, değilse data döner. */
function unwrap<T>(env: Envelope<T>, fallback: T): T {
  if (env.error) throw new Error(env.error);
  return env.data ?? fallback;
}

export async function fetchTriggerMeta(): Promise<TriggerMeta> {
  const { data } = await apiClient.get<Envelope<TriggerMeta>>("/tetikler/meta");
  return unwrap(data, {
    action_kinds: [],
    event_kinds: [],
    operators: [],
    metrics: [],
    cascade_triggers: [],
    cooldown_default_minutes: 60,
  });
}

export async function listTriggers(): Promise<TriggerRule[]> {
  const { data } = await apiClient.get<Envelope<{ triggers: TriggerRule[] }>>(
    "/tetikler"
  );
  return unwrap(data, { triggers: [] }).triggers;
}

export async function createTrigger(
  input: TriggerRuleInput
): Promise<TriggerRule> {
  const { data } = await apiClient.post<Envelope<TriggerRule>>(
    "/tetikler",
    input
  );
  return unwrap(data, {} as TriggerRule);
}

export async function updateTrigger(
  id: string,
  input: Partial<TriggerRuleInput>
): Promise<TriggerRule> {
  const { data } = await apiClient.patch<Envelope<TriggerRule>>(
    `/tetikler/${id}`,
    input
  );
  return unwrap(data, {} as TriggerRule);
}

export async function deleteTrigger(id: string): Promise<void> {
  const { data } = await apiClient.delete<Envelope<{ deleted: boolean }>>(
    `/tetikler/${id}`
  );
  unwrap(data, { deleted: false });
}

export async function listTriggerRuns(
  triggerId?: string,
  limit = 50
): Promise<TriggerRun[]> {
  const { data } = await apiClient.get<Envelope<{ runs: TriggerRun[] }>>(
    "/tetikler/runs",
    { params: { trigger_id: triggerId, limit } }
  );
  return unwrap(data, { runs: [] }).runs;
}

/** Koşulu örnek değerlerle değerlendirir — aksiyon çalışmaz, satır yazılmaz. */
export async function dryRunCondition(
  condition: TriggerCondition,
  values: Record<string, number>
): Promise<DryRunResult> {
  const { data } = await apiClient.post<Envelope<DryRunResult>>(
    "/tetikler/dry-run",
    { condition, values }
  );
  return unwrap(data, { would_fire: false, unknown_metrics: [], condition });
}

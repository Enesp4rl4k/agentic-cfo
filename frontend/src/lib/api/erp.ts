import { apiClient } from "@/lib/api/client";

// ── Types ──────────────────────────────────────────────────────────────────────

export type ERPProvider = "parasut" | "logo_tiger" | "mikro" | "netsis";
export type ERPStatus = "pending" | "active" | "error" | "disconnected" | "expired";
export type SyncStatus = "success" | "error" | "partial" | "running";

export interface ERPIntegration {
  id:                  string;
  org_id:              string;
  provider:            ERPProvider;
  display_name:        string;
  status:              ERPStatus;
  last_sync_at:        string | null;
  last_sync_status:    SyncStatus | null;
  last_sync_count:     number | null;
  last_error:          string | null;
  next_sync_at:        string | null;
  auto_sync_enabled:   boolean;
  sync_interval_hours: number;
  connected_at:        string | null;
  token_expires_at:    string | null;
  token_expired:       boolean;
}

export interface ERPSyncLog {
  id:                    string;
  integration_id:        string;
  provider:              ERPProvider;
  status:                SyncStatus;
  transactions_synced:   number;
  transactions_skipped:  number;
  error_message:         string | null;
  triggered_cfo_job_id:  string | null;
  started_at:            string;
  finished_at:           string | null;
  duration_seconds:      number | null;
}

export interface ERPSyncResult {
  ok:               boolean;
  integration_id?:  string;
  transactions?:    Record<string, unknown>[];
  sync_count:       number;
  skipped?:         number;
  parse_errors?:    string[];
  cfo_job_id?:      string | null;
  error?:           string;
  statement_info?: {
    bank_name?:      string;
    account_number?: string;
    period_start?:   string | null;
    period_end?:     string | null;
  };
}

// ── List & Get ────────────────────────────────────────────────────────────────

export async function listERPIntegrations(): Promise<{
  integrations: ERPIntegration[];
  providers:    string[];
}> {
  const res = await apiClient.get("/erp/integrations");
  return res.data as Awaited<ReturnType<typeof listERPIntegrations>>;
}

export async function getERPIntegration(id: string): Promise<ERPIntegration> {
  const res = await apiClient.get<ERPIntegration>(`/erp/integrations/${id}`);
  return res.data;
}

export async function deleteERPIntegration(id: string): Promise<{ ok: boolean; deleted_id: string }> {
  const res = await apiClient.delete(`/erp/integrations/${id}`);
  return res.data as Awaited<ReturnType<typeof deleteERPIntegration>>;
}

// ── Paraşüt ───────────────────────────────────────────────────────────────────

export interface ParasutConnectRequest {
  client_id:     string;
  client_secret: string;
  company_id:    string;
  redirect_uri:  string;
}

export async function connectParasut(req: ParasutConnectRequest): Promise<{
  auth_url: string;
  state:    string;
}> {
  const res = await apiClient.post("/erp/parasut/connect", req);
  return res.data as Awaited<ReturnType<typeof connectParasut>>;
}

export async function syncParasut(integrationId: string): Promise<ERPSyncResult> {
  const formData = new FormData();
  formData.append("integration_id", integrationId);
  const res = await apiClient.post<ERPSyncResult>("/erp/parasut/sync", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

export async function disconnectParasut(integrationId: string): Promise<{ ok: boolean }> {
  const res = await apiClient.post(`/erp/parasut/disconnect?integration_id=${integrationId}`);
  return res.data as Awaited<ReturnType<typeof disconnectParasut>>;
}

// ── Logo Tiger ────────────────────────────────────────────────────────────────

export async function connectLogoTiger(displayName?: string): Promise<ERPIntegration> {
  const res = await apiClient.post<ERPIntegration>("/erp/logo-tiger/connect", {
    display_name: displayName ?? "Logo Tiger",
  });
  return res.data;
}

export async function syncLogoTiger(file: File): Promise<ERPSyncResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await apiClient.post<ERPSyncResult>("/erp/logo-tiger/sync", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

// ── Mikro ERP ─────────────────────────────────────────────────────────────────

export async function syncMikro(file: File): Promise<ERPSyncResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await apiClient.post<ERPSyncResult>("/erp/mikro/sync", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

// ── Sync logs ─────────────────────────────────────────────────────────────────

export async function getERPSyncLogs(
  provider?: ERPProvider,
  limit = 20,
): Promise<{ logs: ERPSyncLog[] }> {
  const params = new URLSearchParams();
  if (provider) params.set("provider", provider);
  params.set("limit", String(limit));
  const res = await apiClient.get(`/erp/sync-logs?${params.toString()}`);
  return res.data as Awaited<ReturnType<typeof getERPSyncLogs>>;
}

// ── Display helpers ───────────────────────────────────────────────────────────

export const ERP_PROVIDER_LABELS: Record<ERPProvider, string> = {
  parasut:    "Paraşüt",
  logo_tiger: "Logo Tiger",
  mikro:      "Mikro ERP",
  netsis:     "Netsis",
};

export const ERP_PROVIDER_DESCRIPTIONS: Record<ERPProvider, string> = {
  parasut:    "Cloud muhasebe — OAuth2 API entegrasyonu",
  logo_tiger: "Logo Tiger — CSV export yükleme",
  mikro:      "Mikro ERP — CSV export yükleme",
  netsis:     "Netsis — CSV export yükleme",
};

export function statusColor(status: ERPStatus): string {
  switch (status) {
    case "active":       return "text-emerald-400";
    case "pending":      return "text-yellow-400";
    case "error":        return "text-red-400";
    case "expired":      return "text-orange-400";
    case "disconnected": return "text-muted-foreground";
    default:             return "text-muted-foreground";
  }
}

export function statusBg(status: ERPStatus): string {
  switch (status) {
    case "active":       return "bg-emerald-500/10 border-emerald-500/30";
    case "pending":      return "bg-yellow-500/10 border-yellow-500/30";
    case "error":        return "bg-red-500/10 border-red-500/30";
    case "expired":      return "bg-orange-500/10 border-orange-500/30";
    case "disconnected": return "bg-muted/50 border-border";
    default:             return "bg-muted/50 border-border";
  }
}

export function syncStatusColor(status: SyncStatus | null): string {
  switch (status) {
    case "success": return "text-emerald-400";
    case "error":   return "text-red-400";
    case "partial": return "text-yellow-400";
    case "running": return "text-blue-400";
    default:        return "text-muted-foreground";
  }
}

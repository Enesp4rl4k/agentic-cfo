import { apiClient } from "@/lib/api/client";

// ── Connector Platform (Faz 13) ────────────────────────────────────────────────

export interface ConnectorStatus {
  name: string;
  domain: string;
  kernel_role: string | null;
  connected: boolean;
  status: string;
  last_sync_at: string | null;
  last_record_count: number | null;
  last_error: string | null;
}

export interface ConnectorSyncResult {
  connector: string;
  ok: boolean;
  sync_run_id: string | null;
  records_fetched: number;
  records_written: number;
  warnings: string[];
  error: string | null;
}

export async function listConnectors(): Promise<ConnectorStatus[]> {
  const res = await apiClient.get<{ data: { connectors: ConnectorStatus[] } }>(
    "/connectors"
  );
  return res.data.data.connectors;
}

export async function connectConnector(
  name: string,
  body: { config: Record<string, unknown>; secret: Record<string, unknown>; display_name?: string }
): Promise<{ status: string; account: string | null; detail: string }> {
  const res = await apiClient.post<{ data: { status: string; account: string | null; detail: string } }>(
    `/connectors/${name}/connect`,
    body
  );
  return res.data.data;
}

export async function syncConnector(
  name: string,
  runKernel = true
): Promise<{ sync: ConnectorSyncResult; kernel: unknown }> {
  const res = await apiClient.post<{ data: { sync: ConnectorSyncResult; kernel: unknown } }>(
    `/connectors/${name}/sync`,
    { run_kernel: runKernel }
  );
  return res.data.data;
}

export async function disconnectConnector(name: string): Promise<void> {
  await apiClient.delete(`/connectors/${name}`);
}

/** What `GET /privacy/overview` answers (backend: app/api/privacy_data.py). */
export type NoticeStatus = {
  version: string;
  url: string | null;
  accepted_version: string | null;
  accepted_at: string | null;
  must_accept: boolean;
};

/** What `GET /privacy/notices` answers; the gate reads `must_accept`, the screens read the rest. */
export type NoticesState = { privacy_notice: NoticeStatus; terms: NoticeStatus; must_accept: boolean };

export type ExportState = {
  export_id: string;
  status: "queued" | "running" | "ready" | "failed" | "expired";
  size_bytes: number | null;
  expires_at: string | null;
  download: string | null;
  error_code: string | null;
};

export type ThirdParty = {
  key: string;
  name: string;
  sends: string;
  masked: boolean;
  switch: string;
  reaches_from: string[];
};

export type RetentionView = {
  platform: Record<string, number>;
  effective: Record<string, number>;
  company_choice: Record<string, number>;
  floor_days: number;
  company_keys: string[];
  dry_run: boolean;
  can_edit: boolean;
};

export type PrivacyOverview = {
  role: string | null;
  third_parties: ThirdParty[];
  notices: NoticesState;
  cooling_off_days: number;
  /** The operator's configured support address or link; null when unset. */
  support_contact: string | null;
  retention: RetentionView;
  export: ExportState | null;
};

export type ErasureRequestRow = {
  request_id: string;
  scope: "org" | "member";
  status: "pending" | "scheduled" | "executing" | "cleanup_pending" | "failed" | "blocked";
  execute_after: string | null;
  about_me: boolean;
  cancellable: boolean;
  /** Fixed codes for the support desk; never shown to the person as text. */
  failure_code?: string | null;
  blocked_reason?: string | null;
};

/** The server's reason for a refusal, when it sent one. */
export function detailOf(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  // The shared API client rethrows an Error whose message IS the server's detail and which carries the HTTP status.
  const err = error as { status?: unknown; message?: unknown } | null;
  return typeof err?.status === "number" && typeof err.message === "string" ? err.message : null;
}

export function statusOf(error: unknown): number | null {
  const status = (error as { status?: unknown; response?: { status?: unknown } } | null);
  const code = status?.status ?? status?.response?.status;
  return typeof code === "number" ? code : null;
}

export async function downloadBlob(
  get: (path: string, config: { responseType: "blob" }) => Promise<{ data: unknown }>,
  path: string,
  fileName: string,
): Promise<void> {
  const res = await get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

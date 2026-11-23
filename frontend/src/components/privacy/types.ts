/** What `GET /privacy/overview` answers (backend: app/api/privacy_data.py). */
export type NoticeStatus = {
  version: string;
  url: string | null;
  accepted_version: string | null;
  accepted_at: string | null;
  must_accept: boolean;
};

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
  notices: { privacy_notice: NoticeStatus; terms: NoticeStatus; must_accept: boolean };
  cooling_off_days: number;
  retention: RetentionView;
  export: ExportState | null;
};

export type ErasureRequestRow = {
  request_id: string;
  scope: "org" | "member";
  status: "pending" | "scheduled";
  execute_after: string | null;
  about_me: boolean;
  cancellable: boolean;
};

/** The server's reason for a refusal, when it sent one. */
export function detailOf(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : null;
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

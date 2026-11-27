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

export type AiEgressView = {
  mode: "off" | "masked" | "raw";
  source: "platform" | "organisation";
  platform_mode: "off" | "masked" | "raw";
  organisation_choice: "off" | "masked" | "raw" | null;
  choice_capped: boolean;
  allowed_modes: string[];
  provider_host: string | null;
  provider_is_local: boolean;
  model: string;
  /** The model ids the tiers really call (a tier override wins over LLM_MODEL). */
  models: string[];
  document_text: "allow" | "never";
  categories: { key: string; state: "sent" | "replaced" | "partly" | "not_sent" }[];
  /** Counts only: calls that sent something and the bytes sent in the last `days` days. */
  usage: {
    days: number; calls: number; bytes_out: number; calls_by_mode: Record<string, number>;
    /** Calls masked mode refused (fail closed: nothing was sent), by reason. */
    refused: Record<string, number>; refused_total: number;
  };
  dictionary: { known_names: number; truncated: boolean; complete: boolean } | null;
  /** Stored embeddings not made under the current mode / pseudonym key: re-embedded by the maintenance job. */
  embeddings: { pending_reindex: number };
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
  /** The owner's "Yapay zekâya giden veri" view; null for everyone else. */
  ai_egress: AiEgressView | null;
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

/** A link is rendered only when it is an absolute http(s) URL; `javascript:`, `data:` and relative values are not links. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return (u.protocol === "https:" || u.protocol === "http:") && u.hostname !== "" ? u.href : null;
  } catch {
    return null;
  }
}

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

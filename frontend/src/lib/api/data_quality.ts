/**
 * Data Quality API client (DQ-1, DQ-2, DQ-3)
 */

import { apiClient } from "./client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ColumnInfo {
  name: string;
  raw_name: string;
  detected_type: "date" | "amount" | "text" | "integer" | "boolean" | "mixed";
  mapped_field: string | null;
  null_count: number;
  null_pct: number;
  sample_values: string[];
  issues: string[];
  date_format: string | null;
}

export interface RowIssue {
  row: number;
  column: string | null;
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
}

export interface ValidationResult {
  health_score: number;        // 0-100
  health_label: "excellent" | "good" | "fair" | "poor" | "critical";
  row_count: number;
  column_count: number;
  encoding: string;
  delimiter: string;
  columns: ColumnInfo[];
  row_issues: RowIssue[];
  column_mapping: Record<string, string>;  // system_field → csv_column
  summary: string;
  recommendations: string[];
  score_breakdown: Record<string, number>;
  error_count: number;
  warning_count: number;
}

export interface ValidateAndUploadResult {
  validation: ValidationResult | null;
  job_id: string | null;
  started: boolean;
  blocked_reason: string | null;
}

export interface FieldMappingHint {
  field: string;
  required: boolean;
  aliases: string[];
  description: string;
}

// ── API functions ─────────────────────────────────────────────────────────────

export async function validateCSV(file: File): Promise<ValidationResult> {
  const form = new FormData();
  form.append("file", file);

  const res = await apiClient.post<{ data: ValidationResult }>("/data-quality/validate", form, {
    headers: { "Content-Type": "multipart/form-data" }
  });
  return res.data.data;
}

export async function validateAndUpload(
  file: File,
  options?: { minScore?: number; force?: boolean; clientId?: string | null }
): Promise<ValidateAndUploadResult> {
  const form = new FormData();
  form.append("file", file);

  const params = new URLSearchParams();
  if (options?.minScore != null) params.set("min_score", String(options.minScore));
  if (options?.force) params.set("force", "true");
  // Which of an accountant's clients this file is for. Without it the upload
  // lands unattributed and the portal cannot show whose work is waiting.
  if (options?.clientId) params.set("client_id", options.clientId);

  const res = await apiClient.post<{ data: ValidateAndUploadResult }>(
    `/data-quality/validate-and-upload?${params.toString()}`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return res.data.data;
}

export async function getFieldMappingHints(): Promise<FieldMappingHint[]> {
  const res = await apiClient.get<{ data: { fields: FieldMappingHint[] } }>("/data-quality/field-mapping-hints");
  return res.data.data.fields;
}

export async function acceptColumnMapping(params: {
  filename: string;
  column_mapping: Record<string, string>;
  csv_content: string;  // base64
  encoding?: string;
  /**
   * The mapping step is where a UI upload actually completes, so the client
   * has to survive it — otherwise the attribution is lost between the two
   * halves of one upload.
   */
  client_id?: string | null;
}): Promise<{ job_id: string; column_mapping: Record<string, string>; status: string }> {
  const res = await apiClient.post<{ data: { job_id: string; column_mapping: Record<string, string>; status: string } }>(
    "/data-quality/accept-mapping",
    params
  );
  return res.data.data;
}

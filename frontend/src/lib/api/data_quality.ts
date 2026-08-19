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

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/data-quality/validate`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("access_token") ?? "" : ""}`,
      },
      body: form,
    }
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }

  const json = await res.json();
  return json.data as ValidationResult;
}

export async function validateAndUpload(
  file: File,
  options?: { minScore?: number; force?: boolean }
): Promise<ValidateAndUploadResult> {
  const form = new FormData();
  form.append("file", file);

  const params = new URLSearchParams();
  if (options?.minScore != null) params.set("min_score", String(options.minScore));
  if (options?.force) params.set("force", "true");

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/data-quality/validate-and-upload?${params}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("access_token") ?? "" : ""}`,
      },
      body: form,
    }
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }

  const json = await res.json();
  return json.data as ValidateAndUploadResult;
}

export async function getFieldMappingHints(): Promise<FieldMappingHint[]> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/data-quality/field-mapping-hints`,
    {
      headers: {
        Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("access_token") ?? "" : ""}`,
      },
    }
  );

  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  return json.data.fields as FieldMappingHint[];
}

export async function acceptColumnMapping(params: {
  filename: string;
  column_mapping: Record<string, string>;
  csv_content: string;  // base64
  encoding?: string;
}): Promise<{ job_id: string; column_mapping: Record<string, string>; status: string }> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/data-quality/accept-mapping`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("access_token") ?? "" : ""}`,
      },
      body: JSON.stringify(params),
    }
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }

  const json = await res.json();
  return json.data;
}

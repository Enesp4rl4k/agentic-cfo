import { apiClient } from "@/lib/api/client";

// ── Confidence decomposition ────────────────────────────────────────────────

export interface ConfidenceComponent {
  step: string;
  confidence: number;
  ok: boolean;
  detail: string | null;
  kind: "skill" | "reflection" | "reconciliation";
  weakest?: boolean;
}

export interface ConfidenceBreakdown {
  aggregate: number;
  threshold: number;
  meets_threshold: boolean;
  binding_constraint: string | null;
  components: ConfidenceComponent[];
  narrative: string;
}

// ── TR accounting vertical (L3 autopilot) ────────────────────────────────────

export interface TrVerticalResult {
  job_id: string;
  stage: "ingest" | "cfo" | "accounting" | "board_deck" | "done";
  approval_required: boolean;
  approval_reasons: string[];
  errors: string[];
  cfo: {
    halted?: boolean;
    awaiting_review?: boolean;
    error?: string | null;
    min_confidence?: number | null;
    pnl?: {
      revenue?: number;
      gross_profit?: number;
      ebitda?: number;
      net_income?: number;
      net_margin?: number;
      narrative?: string;
    } | null;
    anomalies?: Array<{ title?: string; severity?: string; description?: string }>;
    transaction_count?: number;
    confidence_breakdown?: ConfidenceBreakdown | null;
  };
  reconciliation?: {
    action: "proceed" | "hold_for_review" | "halt";
    identity_failures: string[];
    ungrounded_claims: string[];
    notes: string[];
  } | null;
  accounting?: {
    islem_sayisi: number;
    kayit_sayisi: number;
    onay_bekleyen: number;
    dengeli: boolean;
    hata?: string | null;
  } | null;
  board_deck_pdf_size: number;
  board_deck_pdf_path?: string | null;
}

export interface TrVerticalResponse {
  data: TrVerticalResult;
  error: string | null;
  meta: { depth_level: number; auto_approved: boolean };
}

export async function runTrVertical(
  jobId: string,
  opts: { companyName?: string; donem?: string } = {}
): Promise<TrVerticalResponse> {
  const res = await apiClient.post<TrVerticalResponse>("/muhasebe/tr-vertical", {
    job_id: jobId,
    company_name: opts.companyName,
    donem: opts.donem,
  });
  return res.data;
}

export async function downloadTrBoardDeck(jobId: string): Promise<Blob> {
  const res = await apiClient.get(
    `/muhasebe/tr-vertical/${jobId}/board-deck.pdf`,
    { responseType: "blob" }
  );
  return new Blob([res.data], { type: "application/pdf" });
}

// ── LLM cost rollup (observability) ─────────────────────────────────────────

export interface LlmCostBucket {
  key: string | null;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export interface LlmCosts {
  window_days: number;
  total_calls: number;
  ok_calls: number;
  total_cost_usd: number;
  by_model: LlmCostBucket[];
  by_task: LlmCostBucket[];
  by_day: LlmCostBucket[];
}

export async function getLlmCosts(days = 30): Promise<LlmCosts> {
  const res = await apiClient.get<{ data: LlmCosts; error: null }>("/system/llm-costs", {
    params: { days },
  });
  return res.data.data;
}

// ── e-Defter (XBRL GL) ──────────────────────────────────────────────────────

export type EDefterKind = "yevmiye" | "kebir";

export interface EDefterFile {
  blob: Blob;
  /** GİB naming: VKN-YYYYMM-Y-000000.xml */
  fileName: string;
  entryCount: number;
  lineCount: number;
  /**
   * Signed with a mali mühür and berat obtained? Always false today: the
   * document is structurally complete and legally incomplete, and the UI has
   * to keep those apart rather than let a download imply a filing.
   */
  filable: boolean;
  unfilableCode: string;
  sha256: string;
  /** Entries booked gross because the source stated no KDV amount. */
  kdvUnverified: number;
}

const EDEFTER_ROUTE: Record<EDefterKind, string> = {
  yevmiye: "e-defter.xml",
  kebir: "e-defter-kebir.xml",
};

export async function downloadEDefter(
  jobId: string,
  kind: EDefterKind,
): Promise<EDefterFile> {
  const res = await apiClient.get(`/muhasebe/${jobId}/${EDEFTER_ROUTE[kind]}`, {
    responseType: "blob",
  });
  const h = res.headers as Record<string, string | undefined>;
  // The server names the file to GİB's convention; keeping its name matters,
  // because that name is part of what makes the file identifiable.
  const disposition = h["content-disposition"] ?? "";
  const utf8 = /filename\*=UTF-8''([^;]+)/.exec(disposition)?.[1];
  const plain = /filename="([^"]+)"/.exec(disposition)?.[1];

  return {
    blob: new Blob([res.data], { type: "application/xml" }),
    fileName: utf8 ? decodeURIComponent(utf8) : (plain ?? `e-defter-${kind}.xml`),
    entryCount: Number(h["x-edefter-entry-count"] ?? 0),
    lineCount: Number(h["x-edefter-line-count"] ?? 0),
    filable: h["x-edefter-filable"] === "true",
    unfilableCode: h["x-edefter-unfilable-code"] ?? "",
    sha256: h["x-edefter-sha256"] ?? "",
    kdvUnverified: Number(h["x-edefter-kdv-unverified"] ?? 0),
  };
}

export interface BeratPreview {
  blob: Blob;
  fileName: string;
  /** The defter file this berat was derived from. */
  of: string;
  uniqueId: string;
  sizeMiB: string;
  unfilableCode: string;
}

/**
 * The berat for this job's ledger — a preview. Its binding value is the
 * defter's signature, which an unsigned defter does not have, so it is
 * regenerated from the signed file before it can be filed.
 */
export async function downloadBeratPreview(
  jobId: string,
  kind: EDefterKind,
): Promise<BeratPreview> {
  const res = await apiClient.get(`/muhasebe/${jobId}/e-defter-berat.xml`, {
    params: { kind },
    responseType: "blob",
  });
  const h = res.headers as Record<string, string | undefined>;
  const disposition = h["content-disposition"] ?? "";
  const utf8 = /filename\*=UTF-8''([^;]+)/.exec(disposition)?.[1];
  const plain = /filename="([^"]+)"/.exec(disposition)?.[1];
  return {
    blob: new Blob([res.data], { type: "application/xml" }),
    fileName: utf8 ? decodeURIComponent(utf8) : (plain ?? `berat-${kind}.xml`),
    of: h["x-edefter-berat-of"] ?? "",
    uniqueId: h["x-edefter-berat-unique-id"] ?? "",
    sizeMiB: h["x-edefter-berat-size-mib"] ?? "",
    unfilableCode: h["x-edefter-unfilable-code"] ?? "",
  };
}

export interface EDefterStep {
  key: string;
  label: string;
  done: boolean;
  /** A draft exists, but the step is not done. */
  preview?: boolean;
  detail: string;
}

export interface EDefterDurum {
  job_id: string;
  filable: boolean;
  steps: EDefterStep[];
  next_step: string | null;
}

export async function getEDefterDurum(jobId: string): Promise<EDefterDurum> {
  const res = await apiClient.get(`/muhasebe/${jobId}/e-defter/durum`);
  return res.data.data;
}

/**
 * Has this job been through the accounting chain?
 *
 * The autopilot result only lives in page state, so a user who runs it, walks
 * to the approval queue and comes back finds an empty page — and the sealed
 * packet and the e-Defter built from it become unreachable without re-running
 * the whole pipeline. This is the cheap question that lets the page recover:
 * approved journal entries exist for this job, therefore the tail of the chain
 * is real and should be on screen.
 */
export async function hasApprovedJournal(jobId: string): Promise<boolean> {
  try {
    const res = await apiClient.get<{ data: { kayit_sayisi?: number } }>(
      `/muhasebe/mizan/${jobId}`,
    );
    return (res.data.data?.kayit_sayisi ?? 0) > 0;
  } catch {
    return false;
  }
}

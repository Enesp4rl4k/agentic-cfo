import { apiClient } from "@/lib/api/client";

// ── Yetki Matrisi (Delegation of Authority) ────────────────────────────────

export interface AuthorityRule {
  id: string;
  domain: "journal_entry" | "spending" | "hiring" | "agent_recommendation" | "*";
  when: Record<string, unknown>;
  decision: "auto_approve" | "require_approvals" | "block";
  approvals?: Array<{ role: string; count: number }>;
  require_evidence?: string[];
  note?: string;
}

export interface AuthorityPolicy {
  is_default: boolean;
  id?: string;
  version: number;
  rules: AuthorityRule[];
  note?: string | null;
  updated_at?: string | null;
}

export interface AuthorityDecision {
  outcome: "auto_approve" | "needs_approval" | "blocked";
  matched_rule_id: string | null;
  required_approvals: Array<{ role: string; count: number }>;
  required_evidence: string[];
  rationale: string;
}

export interface PolicyVersion {
  id: string;
  version: number;
  active: boolean;
  note: string | null;
  rule_count: number;
  created_by: string | null;
  created_at: string | null;
}

export async function getAuthorityPolicy(): Promise<AuthorityPolicy> {
  const res = await apiClient.get<{ data: AuthorityPolicy }>("/authority/policy");
  return res.data.data;
}

export async function putAuthorityPolicy(
  rules: AuthorityRule[],
  note?: string
): Promise<{ id: string; version: number }> {
  const res = await apiClient.put<{ data: { id: string; version: number } }>(
    "/authority/policy",
    { rules, note }
  );
  return res.data.data;
}

export async function evaluateAuthority(
  req: Partial<{
    domain: string;
    amount_kurus: number;
    category: string;
    counterparty: string;
    is_related_party: boolean;
    is_fixed_asset: boolean;
    confidence: number;
    classification_method: string;
    requested_by_role: string;
  }>
): Promise<AuthorityDecision> {
  const res = await apiClient.post<{ data: AuthorityDecision }>(
    "/authority/evaluate",
    req
  );
  return res.data.data;
}

export async function getAuthorityVersions(): Promise<PolicyVersion[]> {
  const res = await apiClient.get<{ data: { versions: PolicyVersion[] } }>(
    "/authority/policy/versions"
  );
  return res.data.data.versions;
}

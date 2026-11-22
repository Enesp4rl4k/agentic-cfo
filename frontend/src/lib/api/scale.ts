import { apiClient } from "@/lib/api/client";

// What the company's size sets, and who the accountant is (backend app/api/materiality.py,
// briefing_recipients.py, smmm_workload.py). Every write here is an owner/admin decision with a record.

export type MaterialitySource = "measured" | "declared" | "legacy" | "owner_override";

export interface MaterialityCurrent {
  threshold_cents: number;
  currency: string;
  source: MaterialitySource;
  /** False until an owner or admin acknowledged a value: the fixed amount still applies. */
  acknowledged: boolean;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  /** The sentence that says where the value comes from: "… aylık ortalama çıkışı X'in %5'i = Y". */
  basis_text: string;
}

export interface MaterialityProposal {
  amount_cents: number;
  currency: string;
  source: "measured" | "declared";
  basis_text: string;
  differs_from_current: boolean;
}

export interface Materiality {
  current: MaterialityCurrent;
  rule: { ratio: number; floor_cents: number; ceiling_cents: number; legacy_cents: number };
  can_decide: boolean;
  proposal: MaterialityProposal | null;
}

export interface BriefingRecipients {
  send_to_smmm: boolean;
  has_smmm: boolean;
  /** The size profile's suggestion; a suggestion only. */
  suggested: boolean;
}

export interface WorkloadOrg {
  org_id: string;
  name: string;
  pending_onay: number;
  month_to_close: string | null;
  briefings_held: number;
  waiting: number;
}

export interface Workload {
  organizations: WorkloadOrg[];
  total_waiting: number;
}

type Envelope<T> = { data: T; error: string | null };

export async function getMateriality(): Promise<Materiality> {
  return (await apiClient.get<Envelope<Materiality>>("/org/me/materiality")).data.data;
}

export async function acknowledgeMateriality(amountCents: number): Promise<Materiality> {
  return (await apiClient.post<Envelope<Materiality>>("/org/me/materiality/acknowledge", { amount_cents: amountCents })).data.data;
}

export async function setMateriality(amountCents: number, reason?: string): Promise<Materiality> {
  return (await apiClient.put<Envelope<Materiality>>("/org/me/materiality", { amount_cents: amountCents, reason: reason || null })).data.data;
}

export async function getBriefingRecipients(): Promise<BriefingRecipients> {
  return (await apiClient.get<Envelope<BriefingRecipients>>("/org/me/briefing-recipients")).data.data;
}

export async function setBriefingToSmmm(sendToSmmm: boolean): Promise<BriefingRecipients> {
  return (await apiClient.put<Envelope<BriefingRecipients>>("/org/me/briefing-recipients", { send_to_smmm: sendToSmmm })).data.data;
}

export async function getSmmmWorkload(): Promise<Workload> {
  return (await apiClient.get<Envelope<Workload>>("/smmm/workload")).data.data;
}

import { apiClient } from "@/lib/api/client";

// The organisations the signed-in user may act in. An accountant (mali
// müşavir) belongs to their own and to each client's; they act in one at a time
// and switch here. Backend: GET /org/memberships, POST /org/switch.

export interface OrgMembership {
  org_id: string;
  name: string;
  role: string;
  active: boolean;
}

export interface MembershipList {
  active_org_id: string | null;
  memberships: OrgMembership[];
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function getMemberships(): Promise<MembershipList> {
  const res = await apiClient.get<Envelope<MembershipList>>("/org/memberships");
  return res.data.data;
}

export async function switchOrg(orgId: string): Promise<{ org_id: string; name: string; role: string }> {
  const res = await apiClient.post<Envelope<{ org_id: string; name: string; role: string }>>(
    "/org/switch",
    { org_id: orgId },
  );
  return res.data.data;
}

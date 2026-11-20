import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/pilot-schema";

/** Where an organisation stands on its first steps — facts, read from its data. */
/** Generated from the backend's schema; see pilot-schema.ts. */
export type BaslangicDurumu = components["schemas"]["Baslangic"];

export async function baslangicDurumu(): Promise<BaslangicDurumu> {
  const res = await apiClient.get<{ data: BaslangicDurumu; error: string | null }>("/baslangic");
  return res.data.data;
}

export async function firmaOlustur(ad: string): Promise<void> {
  await apiClient.post("/org/create", { name: ad });
}

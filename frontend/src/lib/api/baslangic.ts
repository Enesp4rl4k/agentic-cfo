import { apiClient } from "@/lib/api/client";

/** Where an organisation stands on its first steps — facts, read from its data. */
export interface BaslangicDurumu {
  firma: { var: boolean; ad: string | null };
  veri: { analiz_sayisi: number; parasut_bagli: boolean };
  son_analiz: {
    id: string;
    durum: string;
    onay_bekliyor: boolean;
    guven: number | null;
    dosya: string;
    hata: string | null;
    olusturma: string | null;
  } | null;
  tamamlanan_analiz: number;
  otomatik: { eposta: boolean; parasut_otomatik: boolean };
}

export async function baslangicDurumu(): Promise<BaslangicDurumu> {
  const res = await apiClient.get<{ data: BaslangicDurumu; error: string | null }>("/baslangic");
  return res.data.data;
}

export async function firmaOlustur(ad: string): Promise<void> {
  await apiClient.post("/org/create", { name: ad });
}

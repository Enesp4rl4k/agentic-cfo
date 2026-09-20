"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { CircleAlert, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { analyzeWorkingCapital } from "@/lib/api/analytics";
import type { WorkingCapitalMetrik, WorkingCapitalResult } from "@/lib/api/analytics";

/**
 * Nakit döngüsü — hesaplanan, kaynağı gösterilen.
 *
 * This page used to send the figures below to an endpoint that ignored them
 * and answered every company with the same four constants, in a shape the page
 * did not read. It then drew them against a "sector average" nothing measured,
 * a cash-release "opportunity" and a list of recommendations. What is left is
 * what can be computed from what the person typed, each number next to the
 * formula it came from.
 */
const ALANLAR = [
  { key: "accounts_receivable_try", label: "Alacaklar (tahsil edilmemiş faturalar)", ornek: "500000" },
  { key: "annual_revenue_try", label: "Yıllık ciro", ornek: "12000000" },
  { key: "accounts_payable_try", label: "Borçlar (ödenmemiş tedarikçi faturaları)", ornek: "300000" },
  { key: "annual_cogs_try", label: "Yıllık satılan malın maliyeti", ornek: "7200000" },
  { key: "inventory_try", label: "Stok (yoksa 0)", ornek: "0" },
] as const;

const gun = (m: WorkingCapitalMetrik) => (m.gun === null ? "—" : `${m.gun.toFixed(1)} gün`);

export default function WorkingCapitalPage() {
  const [form, setForm] = useState<Record<string, string>>({
    accounts_receivable_try: "", annual_revenue_try: "",
    accounts_payable_try: "", annual_cogs_try: "", inventory_try: "0",
  });
  const [sonuc, setSonuc] = useState<WorkingCapitalResult | null>(null);
  const [yukleniyor, setYukleniyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);

  const sayi = (k: string) => Number.parseFloat(form[k]) || 0;

  async function calistir(e: React.FormEvent) {
    e.preventDefault();
    setYukleniyor(true);
    setHata(null);
    try {
      setSonuc(await analyzeWorkingCapital({
        accounts_receivable_try: sayi("accounts_receivable_try"),
        annual_revenue_try: sayi("annual_revenue_try"),
        accounts_payable_try: sayi("accounts_payable_try"),
        annual_cogs_try: sayi("annual_cogs_try"),
        inventory_try: sayi("inventory_try"),
      }));
    } catch (err) {
      setHata(err instanceof Error ? err.message : "Hesaplanamadı.");
    } finally {
      setYukleniyor(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Nakit Döngüsü</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Paranızın kaç gün işletmede bağlı kaldığını, bilançonuzdaki dört rakamdan hesaplar.
          Her sonucun yanında hangi formülle çıktığı yazar.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <Card className="h-fit p-4">
          <form onSubmit={calistir} className="space-y-3">
            {ALANLAR.map(({ key, label, ornek }) => (
              <div key={key} className="space-y-1">
                <label htmlFor={key} className="text-xs text-muted-foreground">{label}</label>
                <Input
                  id={key}
                  type="number"
                  min={0}
                  inputMode="numeric"
                  placeholder={ornek}
                  value={form[key]}
                  onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                  className="font-mono tabular-nums"
                />
              </div>
            ))}
            <Button type="submit" className="w-full" disabled={yukleniyor}>
              {yukleniyor && <Loader2 className="h-4 w-4 animate-spin" />}
              Hesapla
            </Button>
            {hata && <p className="text-xs text-destructive">{hata}</p>}
          </form>
        </Card>

        <div className="space-y-4">
          {sonuc === null ? (
            <Card className="p-6">
              <p className="text-sm text-muted-foreground">
                Rakamları girip hesaplayın. DSO (tahsilat süresi), DPO (ödeme süresi), DIO (stokta
                kalma süresi) ve bunların birleşimi olan nakit döngüsü hesaplanır.
              </p>
            </Card>
          ) : (
            <>
              {sonuc.eksik_girdiler.length > 0 && (
                <Alert variant="warning">
                  <CircleAlert className="h-4 w-4" />
                  <AlertTitle>Eksik rakam var</AlertTitle>
                  <AlertDescription className="mt-1">
                    {sonuc.eksik_girdiler.join(", ")} girilmeden bu satırlar hesaplanamaz. Tahmini bir
                    değer yazmak yerine boş bırakıldı.
                  </AlertDescription>
                </Alert>
              )}

              <Card className="divide-y">
                {[sonuc.metrikler.dso, sonuc.metrikler.dpo, sonuc.metrikler.dio, sonuc.metrikler.ccc].map((m) => (
                  <div key={m.ad} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 p-4">
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{m.ad}</p>
                      <p className="text-xs text-muted-foreground">{m.aciklama}</p>
                      <p className="mt-1 font-mono text-[11px] text-muted-foreground/80">{m.formul}</p>
                    </div>
                    <p className="text-xl font-semibold tabular-nums">{gun(m)}</p>
                  </div>
                ))}
              </Card>

              <Card className="p-4">
                <p className="text-sm">{sonuc.yorum}</p>
                <p className="mt-2 text-xs text-muted-foreground">{sonuc.sektor_karsilastirmasi_notu}</p>
              </Card>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

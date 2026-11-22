"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useI18n } from "@/hooks/useI18n";

export default function BillingSuccessPage() {
  const params = useSearchParams();
  const { t } = useI18n();
  const plan = params.get("plan");

  return (
    <main className="mx-auto max-w-lg space-y-6 p-8 text-center">
      <h1 className="text-2xl font-bold">{t.billingSuccess.title}</h1>
      <p className="text-muted-foreground">
        {plan
          ? t.billingSuccess.bodyPlan.replace("{plan}", plan)
          : t.billingSuccess.body}
      </p>
      <div className="flex justify-center gap-3">
        <Link href="/billing" className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted">
          {t.billingSuccess.back}
        </Link>
        <Link href="/command-center" className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">
          {t.billingSuccess.open}
        </Link>
      </div>
    </main>
  );
}

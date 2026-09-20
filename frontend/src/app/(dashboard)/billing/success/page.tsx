"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

export default function BillingSuccessPage() {
  const params = useSearchParams();
  const plan = params.get("plan");

  return (
    <main className="mx-auto max-w-lg space-y-6 p-8 text-center">
      <h1 className="text-2xl font-bold">Subscription activated</h1>
      <p className="text-muted-foreground">
        {plan
          ? `Your ${plan} plan checkout completed. It may take a moment for Stripe to sync.`
          : "Your checkout completed. Welcome aboard."}
      </p>
      <div className="flex justify-center gap-3">
        <Link href="/billing" className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted">
          Back to billing
        </Link>
        <Link href="/command-center" className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">
          Open Command Center
        </Link>
      </div>
    </main>
  );
}

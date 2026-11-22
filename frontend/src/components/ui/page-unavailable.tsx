"use client";

import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import { APP_HOME } from "@/lib/routes";

/** What an unknown address, or a switched-off legacy dashboard, shows: no data, no numbers, one way back. */
export function PageUnavailable() {
  const { t } = useI18n();
  return (
    <main className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center gap-3 p-6 text-center">
      <h1 className="text-xl font-semibold text-foreground">{t.notFound.title}</h1>
      <p className="text-sm text-muted-foreground">{t.notFound.body}</p>
      <Link href={APP_HOME} className="text-sm font-medium text-primary hover:underline">
        {t.notFound.home}
      </Link>
    </main>
  );
}

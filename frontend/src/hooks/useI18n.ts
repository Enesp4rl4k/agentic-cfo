"use client";

import { useMemo } from "react";
import { getMessages, resolveAppLocale, type AppLocale, type MessageTree } from "@/lib/i18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";

export function useI18n(): { locale: AppLocale; t: MessageTree } {
  const { org } = useOrgSettings();
  const locale = resolveAppLocale(org?.locale);
  const t = useMemo(() => getMessages(locale), [locale]);
  return { locale, t };
}

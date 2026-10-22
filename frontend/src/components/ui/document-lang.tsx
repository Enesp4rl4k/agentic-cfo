"use client";

import { useEffect } from "react";
import { useI18n } from "@/hooks/useI18n";

/**
 * Keep `<html lang>` in sync with the resolved org locale.
 *
 * The server renders `lang="tr"` (Turkish-first default); once org settings
 * resolve, this corrects it — so `text-transform: uppercase` applies Turkish
 * casing ("KARAR BRİFİ", not "KARAR BRIFI") and assistive tech announces the
 * right language. Rendered from the dashboard layout, where i18n already runs.
 */
export function DocumentLang() {
  const { locale } = useI18n();
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  return null;
}

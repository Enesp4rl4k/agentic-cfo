import { en, type MessageTree } from "./messages/en";
import { tr } from "./messages/tr";

export type AppLocale = "en" | "tr";

const DICTS: Record<AppLocale, MessageTree> = { en, tr };

export function resolveAppLocale(orgLocale?: string | null): AppLocale {
  if (!orgLocale) return "en";
  const lower = orgLocale.toLowerCase();
  if (lower.startsWith("tr")) return "tr";
  return "en";
}

export function getMessages(locale: AppLocale = "en"): MessageTree {
  return DICTS[locale] ?? en;
}

export type { MessageTree };

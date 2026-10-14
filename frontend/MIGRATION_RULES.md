# i18n migration rules (Group D/E pages)

You are migrating ONE Next.js dashboard page from hardcoded strings to the i18n message tree,
and you may need to CREATE your page's message namespace first.
Work in `C:\Users\eparl\Downloads\agentic-cfo\frontend`.

## 1. Read the existing pattern first
`src/lib/i18n/messages/en.ts` declares `MessageTree` (the type, top of file) and then the English
values. `src/lib/i18n/messages/tr.ts` holds the Turkish values with the SAME shape.
Read a couple of existing namespaces (e.g. `budget`, `reports`, `notifications`) to copy the style.

## 2. Create/extend your namespace
If your page's namespace does not exist, add it in BOTH files:
- `en.ts` — add the key to the `MessageTree` type **and** the English value block.
- `tr.ts` — add the same keys with Turkish values.

Rules that are mechanically enforced (do not skip):
- **The `tr` and `en` trees must be structurally identical.** Every leaf key present in one must be
  present in the other (there is a `collectLeafPaths` parity test in `src/__tests__/i18n.test.ts`).
- **The type must match the values.** If you add a key to the type you must add its value, and vice
  versa — otherwise `npx tsc --noEmit` fails.
- Prefer a **flat top-level namespace per page** (`smmm`, `audit`, `risk`, `simulation`, …) with
  nested groups for sections (`empty`, `filters`, `table`, `card`, …).
- Interpolation placeholder style: `{count}`, `{value}`, `{name}` — one style, used in both locales.
  (The one exception: Turkish percent strings encode the `%` as a prefix, e.g. `Güven: %{pct}`.)
- Do not touch any namespace other than your own — other agents may be editing them.

## 3. How to use the tree in the page
```tsx
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat, useCurrencySymbol } from "@/hooks/useCurrencyFormat";
// inside a component:
const { t, locale } = useI18n();
const fmt = useCurrencyFormat();          // formats kuruş(cents integer) → "₺1.234,56"
const symbol = useCurrencySymbol();        // "₺" or "$"
// render: {t.myns.title}
// interpolate: {t.myns.ago.mins.replace("{count}", String(mins))}
```
- `useCurrencyFormat()` takes **kuruş (integer cents)** and returns a localized currency string bound
  to the org's base_currency + locale. NEVER call `formatCurrency(x)` (that is USD-default) and NEVER
  hardcode `₺`/`$`/`TL`/`USD`. Amounts from the backend are almost always kuruş — pass as-is to `fmt`.
- Percent position differs: TR uses `%20` (prefix), EN `20%` (suffix). Encode it in the tree value,
  never hand-build it in JSX.
- `useI18n()` pulls from `useOrgSettings` (react-query). Components that call it need a
  `QueryClientProvider` **or** a `vi.mock("@/hooks/useOrgSettings")` returning `locale: "tr-TR"`
  when rendered in a test (see `src/__tests__/baglan.test.tsx`).

## 4. Locale-bound dates
Replace `toLocaleDateString("tr-TR")` / `toLocaleString("tr-TR")` / `toLocaleTimeString("tr-TR")`
with the active locale tag:
```tsx
const dateTag = locale === "tr" ? "tr-TR" : "en-US";
...toLocaleDateString(dateTag, {...})
```

## 5. What counts as UI copy → move to tree
All user-visible text: headings, labels, buttons, empty states, tooltips, aria-labels, badges,
status words, "x ago" strings, chart series names, table headers, select options, dialog titles.

**EXEMPT (leave as-is):**
- backend/data values (e.g. `a.message`, `narrative`, `issue.message`, `validation.summary`,
  `blocked_reason`, template `columns`, ERP provider keys) — these are data, not our copy.
- detection/filter logic that matches on backend strings (e.g. `includes("runway")`).
- comment lines and sample/fixture CSV content.
If you truly must leave a hardcoded string, add a `// i18n-exempt: <reason>` comment on that line.

## 6. Severity/level badges
Use JS `.toUpperCase()` for any uppercase display of dynamic text (CSS `uppercase` prints dotted-İ
under `html lang=tr`). Static ALL-CAPS in tree values is fine.

## 7. Gates
Run and pass before finishing (from `frontend/` dir):
```
npx tsc --noEmit
```
`npx tsc` is mandatory — it is what catches a broken/missing tree key. Do NOT run the full test
suite or lint (they are run centrally at the end of the group to save time).
Do NOT modify any test file. Only edit your own page file(s) and your own namespace in en.ts/tr.ts.

## 8. Report back
Reply with: (1) files changed, (2) namespace keys you created, (3) any `// i18n-exempt` lines +
reason, (4) confirmation `npx tsc --noEmit` passed, (5) any string you could not find a key for.

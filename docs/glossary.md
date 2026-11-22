# Glossary: product terms, Turkish and English

The product speaks Turkish by default (`DEFAULT_APP_LOCALE = "tr"`). English is shown only when a
person or their organisation explicitly chose it. All copy lives in `frontend/src/lib/i18n/messages/`;
backend codes are mapped to words in `frontend/src/lib/i18n/codes.ts` (an unmapped code is shown as
"Bilinmeyen durum: <kod>", never as a raw key).

Use one word per concept. If a term below has a Turkish form, the Turkish screens use it every time.

| Concept | Turkish (UI) | English (UI) | Notes |
|---|---|---|---|
| Product name | Tiphys | Tiphys | Proper noun, never translated |
| Weekly decision screen | Command Center | Command Center | Feature name, kept in English in Turkish copy |
| 13-week cash view | Nakit Radarı | Cash Radar | "Nakit Radarı" in titles, "nakit radarı" mid-sentence |
| Company ledger | Şirket defteri | Company ledger | One ledger; uploads merge into it |
| Ledger row | Kayıt | Entry | |
| Possible double payment | Mükerrer (olası mükerrer) | Possible duplicate | "Yinelenen" is used only for repeated webhook events |
| Waiting for a person | Kararınızı bekliyor | Waiting for your decision | The system proposes, a person decides |
| Approval | Onay | Approval | |
| Accountant (Turkey) | SMMM | Certified accountant (SMMM) | Abbreviation kept in both languages |
| Receivable / payable | Alacak / Borç | Receivable / Payable | |
| Due date | Vade | Due date | |
| Weekly report | Bülten | Bulletin | |
| Billing | Faturalama | Billing | Not "faturalandırma" |
| Integrations | Entegrasyonlar | Integrations | |
| C-level dashboards | C-Suite | C-Suite | Legacy; see the PR that introduced this file |
| Data provenance | Gerçek / Tahmin / Benchmark | Actual / Estimate / Benchmark | See `provenance` in the messages |

## Words kept in English on purpose

Product and third-party names (Tiphys, Paraşüt, Logo Tiger, Mikro ERP, Netsis, Slack), acronyms used
as such in Turkish finance (CFO, CEO, EBITDA, NPS, PDF, CSV, VKN/TCKN), and technical terms
(Webhook URL, Monte Carlo, Benchmark). These are allowlisted, each with a reason, in
`frontend/src/__tests__/i18n.test.ts` (`SAME_IN_BOTH_VALUES`). Add to that list only with a reason.

## Rules the tests enforce

- `tr` and `en` have the same keys, and no Turkish value is empty where English has text.
- A Turkish value identical to its English twin fails, unless allowlisted.
- Placeholders such as `{count}` appear in both languages.
- `hardcoded-literals.test.ts`: the number of user-visible string literals in components may only go
  down (baseline in `hardcoded-literals.baseline.json`, 509 at the time of writing). Lower the baseline
  when you move strings to i18n; never raise it.
- `casing-gate.test.ts`: embedded Turkish copy and wrong-cased "I" before a vowel may only go down.

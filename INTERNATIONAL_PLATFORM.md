# International Platform Contract

> **Product:** Agentic Management OS (international-first)  
> **Regional packs:** optional locale modules (Turkey first)

## Principles

1. Core OS never depends on a country-specific API.
2. Money is stored as integer minor units + ISO currency code.
3. UI copy goes through the i18n dictionary (`frontend/src/lib/i18n`).
4. Agent prompts may use `org.locale`; grounding / verifier contracts stay global.
5. Nav and APIs for regional features are pack-gated.

## Org locale fields

| Field | Default | Meaning |
|-------|---------|---------|
| `country_code` | `US` | ISO-3166-1 alpha-2 |
| `base_currency` | `USD` | ISO-4217 |
| `locale` | `en-US` | BCP-47 |
| `regional_packs` | `[]` | e.g. `["tr"]` |

Migration: `024_org_international_locale.py`

## Turkey pack (`tr`)

Enabled when `regional_packs` contains `"tr"`.

Gates:
- API: `/smmm/*`, `/muhasebe/*`, `/efatura/*` via `require_tr_pack`
- Nav: `/smmm`, `/smmm-onay`
- CoA: `TrThpAdapter`; otherwise `GenericCoaAdapter`

## Chart of Accounts

```python
from app.services.regional.coa import get_coa_adapter
adapter = get_coa_adapter(regional_packs=org.regional_packs)
result = adapter.classify(description="...", amount_cents=1000)
```

## Tax lens

`GET /org/me/tax-rates` → pack-aware rate table (`app.services.regional.tax`).

## Golden path (global)

```bash
CSV_FILE=scripts/fixtures/golden_path_sample_en_usd.csv \
BACKEND_URL=... AUTH_TOKEN=... ./scripts/golden-path-e2e.sh
```

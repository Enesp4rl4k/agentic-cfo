# C-Suite interface direction — Karar Atlası

## Product expression

The interface is a decision workspace for distinct management roles, not one universal dashboard. Keep a shared visual language and shell; specialize each role's information order, terminology, key comparisons, and next actions. The recurring product pattern is **status → insight → evidence/source → next action**.

## Visual system

- **Canvas:** warm ink dark surfaces rather than blue-black — a cartographer's desk; cards sit one step above the canvas with quiet, legible dividers, and type reads as parchment rather than cold white.
- **Primary accent:** atlas brass (`--primary`, OKLCH `0.79 0.115 83`) for navigation, focus, and actionable emphasis. Do not use it to imply financial gain.
- **Accent palette:** role and feature accents come from the map family in Tailwind (`brass`, `copper`, `clay`, `sage`, `mapblue`, `parchment`) — restrained cartographic tones, never a rainbow of neon hues per card. Warning sits at orange (hue 60), deliberately apart from brass gold (83). Categorical data sets (transaction categories, severities) may still span hues, because there color speaks in the numbers.
- **Semantic colors:** success, warning, and risk are reserved for their actual financial meaning; never rely on color alone to convey status.
- **Charts:** use `--chart-primary` and `--chart-secondary`, plus direct labels, units, and table alternatives where appropriate.
- **Typography:** Inter is the existing UI face. Use a clear heading/body/data hierarchy, tabular numerals for financial values, and plain Turkish labels; preserve English localization.
- **Numbers:** format money with the organisation's base currency and locale (`useCurrencyFormat`), never a hardcoded symbol — the same amount must not read `$` in one card and `₺` in another. Chart ticks use the same currency symbol as the KPI cards.
- **Geometry:** compact rounded surfaces, thin borders, and restrained elevation. Avoid nested cards, decorative blur, gradient text, and animation without task value.
- **Interaction:** visible focus, semantic controls, keyboard access, responsive layouts, and reduced-motion support are baseline requirements. Navigation sections use native disclosure behavior.
- **Locale:** role headers and localized copy must paint in the org's language on first render. While org settings load, fall back from the last resolved locale to the browser language; never show a wrong-language flash in the position users read first.

## Shared components

- Application shell: consistent C-Suite wordmark, grouped/collapsible navigation, current page context, command search, status, notifications, and account controls.
- Financial metric: label, value, unit/period, optional comparison or source; positive/negative color only when the data defines that meaning.
- Evidence and provenance: distinguish real, estimated, and benchmark data close to the metric or conclusion; make the explanation reachable.
- Insight/alert: explain what changed, why it matters, and a relevant action without overstating confidence.
- Every data-heavy component needs loading, empty, error, and narrow-screen behavior.

## Role-specific hierarchy

- **CFO:** profitability and cash position first; then variance, forecast, anomalies, evidence, and report/detail actions.
- **CEO:** strategic priorities, key trade-offs, cross-functional risk, and decisions needing attention.
- **CTO / CMO / CHRO / COO:** each prioritizes its own operating outcomes and data coverage. Estimated values must remain visibly distinct from connected-source measurements.
- **Risk, audit, compliance, and accounting:** emphasize exposure, traceability, ownership, review state, and the next required control action.

## Current implementation boundary

The first implementation passes update global tokens, the shared dashboard shell and logo, the CFO dashboard, and role-specific page headers/input disclosure for CEO, CTO, CMO, CHRO, and COO. The role pages share the palette and shell but keep distinct decision priorities; their deeper KPI and analytical compositions should continue to be refined in focused passes rather than mechanically restyled as CFO copies.

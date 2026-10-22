# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The product serves Turkish companies that need CFO-grade financial analysis and deeper financial governance without necessarily having an in-house CFO. Management users include CFO/finance, CEO, CTO, CMO, CHRO, COO, risk/audit/compliance roles, and accounting professionals. Their dashboards and information needs differ by role.

## Product Purpose

Provide executive financial analysis and Turkish accounting workflows from company data, alongside governance capabilities that make decisions and financial records more disciplined and traceable.

## Positioning

The product combines executive-role analytical views with Turkish accounting depth (including THP/SMMM and GİB e-Fatura workflows) and a governance layer. Analytics may be real, estimated, or benchmark-based; the interface must make provenance explicit and must not present estimates as connected-source facts.

## Operating Context

Users review P&L, cash flow, forecasts, budget variance, tax timing, anomalies, strategic and operational indicators, and accounting/governance workflows. Data is uploaded or connected; some domain metrics may be estimated when no source is connected.

## Capabilities and Constraints

- Role-specific views exist for CFO, CEO, CTO, CMO, CHRO, and COO, with separate risk, audit, compliance, and Turkish accounting surfaces.
- CFO coverage includes P&L, cash flow, forecast, budget variance, tax calendar, and anomaly detection.
- Source provenance is meaningful: real, estimated, and benchmark data must remain distinguishable; synthetic results must not be represented as verified real-world outcomes.
- The frontend is a Next.js 14 / React 18 web application with Turkish and English message catalogs.
- The user wants management-layer dashboards treated as distinct experiences, not collapsed into one generic dashboard. First design scope: shared application shell and dashboard foundation, optimized for faster understanding and decisions.

## Evidence on Hand

- `README.md` documents product purpose, role coverage, provenance rules, and existing workflows.
- Existing role dashboards are implemented under `frontend/src/app/(dashboard)/`.
- Existing visual tokens and the shared app shell are in `frontend/src/styles/globals.css` and `frontend/src/app/(dashboard)/layout.tsx`.
- No customer testimonials or approved outcome benchmarks were identified in the inspected evidence; do not invent them.

## Product Principles

- Tailor information hierarchy to the management role and its decisions.
- Move users from financial state to evidence-backed insight to a clear next action.
- Preserve source provenance and distinguish observed data from estimates and benchmarks.
- Make complex financial and governance workflows understandable without hiding their detail.

## Accessibility & Inclusion

The existing web interface uses semantic HTML and visible keyboard focus styles; preserve and improve keyboard access, readable contrast, and responsive behavior during redesign.

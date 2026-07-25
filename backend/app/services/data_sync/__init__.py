"""
Multi-source data sync pipeline — orchestrates accounting software + banking APIs.

Zero manual uploads → CFO data automatically synchronized.

Phase 1: Accounting software parsers (Paraşüt, Netsis, Mikro, Logo Tiger)
Phase 2: Open Banking APIs (Garanti PSD2, Akbank)
Phase 3: Orchestration + scheduled syncs + data quality checks

Key modules:
  - orchestrator: Main coordination logic
  - accounting: OAuth2 + scheduled parsers for accounting software
  - banking: PSD2 transaction sync + account aggregation
  - validators: Data quality + anomaly detection
  - audit: Immutable sync logs + conflict resolution
"""

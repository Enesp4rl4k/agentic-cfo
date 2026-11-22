"""The per-table half of the personal-data registry (see `registry.py` for the rules and the tests).

Facts here come from reading the models and the code that writes them on `master`; where a flow to a third
party is listed it follows PR #68's call-by-call inventory (`veri-envanteri.md` section 4), which should be
re-verified when a call site changes. Retention classes say what KIND of retention applies; the actual
periods are settings (`app.services.privacy.retention`) or open lawyer questions.
"""
from __future__ import annotations

from app.services.privacy.registry import Category as C
from app.services.privacy.registry import Flow, Retention, Subject, Table

S = Subject
R = Retention
_ID, _CT, _NET, _TAX, _TXT, _DOC, _PSE, _CRED = (
    C.IDENTITY, C.CONTACT, C.NETWORK, C.TAX_ID, C.FREE_TEXT, C.DOCUMENT, C.PSEUDONYM, C.CREDENTIAL,
)

TABLES: dict[str, Table] = {
    # ── people and organisations ────────────────────────────────────────────
    "users": Table("accounts and sign-in", S.MEMBER, R.ACCOUNT,
                   {"email": _CT, "full_name": _ID, "hashed_password": _CRED, "api_key": _CRED, "sso_id": _PSE},
                   (Flow.SSO,), "e-mail and name reach the SMTP provider through outbox mail"),
    "org_memberships": Table("who belongs to which company, in which role", S.MEMBER, R.ACCOUNT, {"user_id": _PSE}),
    "org_invites": Table("invitation of a person to a company", S.MEMBER, R.OPERATIONAL,
                         {"email": _CT, "token": _CRED}, (Flow.SMTP,)),
    "pilot_invites": Table("pilot access codes", S.MEMBER, R.OPERATIONAL, {"email": _CT, "note": _TXT, "used_by_user_id": _PSE}),
    "user_feedback": Table("in-product feedback", S.MEMBER, R.OPERATIONAL,
                           {"user_id": _PSE, "comment": _TXT, "biggest_benefit": _TXT, "biggest_gap": _TXT, "page_context": _TXT}),
    "organizations": Table("the customer company and its billing", S.COMPANY, R.ACCOUNT,
                           {"name": _ID, "slug": _ID, "description": _TXT, "vkn": _TAX, "legal_title": _ID,
                            "logo_url": _TXT, "ip_whitelist": _NET, "stripe_customer_id": _PSE,
                            "stripe_subscription_id": _PSE, "base_currency_confirmed_by": _PSE,
                            "size_profile_set_by": _PSE, "materiality_applied": _PSE},
                           (Flow.LLM, Flow.STRIPE), "the company name is part of chat, SWOT and compliance prompts"),
    "smmm_muhasebeci": Table("an accountant's portal profile", S.ACCOUNTANT, R.ACCOUNT,
                             {"unvan": _ID, "vergi_no": _TAX, "oda_no": _TAX, "firma_adi": _ID, "il": _TXT, "telefon": _CT}),
    "smmm_musteri_kayit": Table("an accountant's client list", S.COUNTERPARTY, R.ACCOUNT,
                                {"firma_adi": _ID, "vergi_no": _TAX, "il": _TXT, "notlar": _TXT}),
    "smmm_hesap_kurallari": Table("an accountant's account-code rules", S.COUNTERPARTY, R.BOOKS, {"anahtar": _ID}),
    # ── the books ──────────────────────────────────────────────────────────
    "analysis_jobs": Table("an uploaded file and its processing", S.ANYONE, R.BOOKS,
                           {"filename": _TXT, "file_path": _TXT, "user_id": _PSE, "smmm_client_id": _PSE, "locked_by": _PSE, "logs": _TXT,
                            "error_message": _TXT, "result_metadata": _TXT},
                           note="the file itself lives under the storage root (see STORES)"),
    "data_sources": Table("an additional uploaded file", S.ANYONE, R.BOOKS, {"filename": _TXT, "file_path": _TXT, "label": _TXT}),
    "transactions": Table("income and expense lines read from documents", S.COUNTERPARTY, R.BOOKS,
                          {"description": _TXT, "vendor": _ID, "counterparty": _ID, "payment_note": _TXT, "raw_text": _DOC},
                          (Flow.LLM,), "description and vendor reach the classifier and chat prompts; raw_text reaches the extraction fallback"),
    "canonical_transactions": Table("the single ledger", S.COUNTERPARTY, R.BOOKS,
                                    {"counterparty": _ID, "description": _TXT}, (Flow.LLM,),
                                    "counterparty and description[:120] are chat evidence"),
    "open_items": Table("receivables and payables", S.COUNTERPARTY, R.BOOKS,
                        {"counterparty": _ID, "description": _TXT, "payment_note": _TXT}, (Flow.LLM,)),
    "open_item_matches": Table("invoice-to-payment matches", S.MEMBER, R.BOOKS, {"decided_by": _PSE}),
    "journal_entries": Table("double-entry journal", S.COUNTERPARTY, R.BOOKS, {"aciklama": _TXT, "onay_neden": _TXT}),
    "journal_lines": Table("journal lines", S.COUNTERPARTY, R.BOOKS, {"aciklama": _TXT}),
    "category_rules": Table("category rules by vendor", S.COUNTERPARTY, R.ACCOUNT, {"vendor_match": _ID, "keyword_match": _TXT}),
    "category_overrides": Table("a person's single-row category corrections", S.MEMBER, R.ACCOUNT, {}),
    "counterparty_aliases": Table("two spellings declared one supplier", S.COUNTERPARTY, R.ACCOUNT,
                                  {"alias_name": _ID, "canonical_name": _ID, "alias_token": _PSE, "canonical_token": _PSE,
                                   "created_by": _PSE, "revoked_by": _PSE}),
    "related_parties": Table("related parties of the company", S.COUNTERPARTY, R.ACCOUNT,
                             {"name": _ID, "normalized_name": _ID, "tax_id": _TAX, "note": _TXT, "created_by": _PSE}),
    "held_transactions": Table("rows the system would not book alone", S.COUNTERPARTY, R.BOOKS,
                               {"payload": _TXT, "resolved_by": _PSE}),
    "direction_mappings": Table("standing answers about a statement's columns", S.MEMBER, R.ACCOUNT,
                                {"reason": _TXT, "answer": _TXT, "flagged_note": _TXT, "created_by": _PSE, "revoked_by": _PSE}),
    "smmm_onay_kayitlari": Table("accountant approvals and corrections", S.COUNTERPARTY, R.BOOKS,
                                 {"orijinal_kayit": _TXT, "onay_notu": _TXT, "duzeltme_aciklama": _TXT, "onay_neden": _TXT,
                                  "tx_description": _TXT, "created_by_user_id": _PSE, "onaylayan_user_id": _PSE}),
    "defensibility_packets": Table("a sealed accountant defensibility packet", S.COUNTERPARTY, R.BOOKS,
                                   {"payload": _TXT, "smmm_statement": _TXT, "summary": _TXT}),
    "payment_plan_changes": Table("proposed changes to a payment plan", S.MEMBER, R.BOOKS,
                                  {"requested_by": _PSE, "request_note": _TXT, "decided_by": _PSE, "decision_note": _TXT}),
    "decisions": Table("who decided what (append-only decision record)", S.MEMBER, R.BOOKS,
                       {"decided_by": _PSE, "reason": _TXT, "before": _TXT, "after": _TXT},
                       note="decided_by is a user id: after member erasure it points at a tombstone with no personal data"),
    "decision_logs": Table("the decision journal", S.MEMBER, R.OPERATIONAL, {"rationale": _TXT, "outcome_note": _TXT, "created_by": _PSE}),
    "authority_policies": Table("who may approve what", S.COMPANY, R.ACCOUNT, {"note": _TXT}),
    "reports": Table("generated reports (files and JSON)", S.COUNTERPARTY, R.BOOKS, {"file_path": _TXT, "data": _TXT}),
    "anomalies": Table("detected anomalies", S.COUNTERPARTY, R.OPERATIONAL,
                       {"title": _TXT, "description": _TXT, "evidence": _TXT}, (Flow.LLM,), "titles name the vendor"),
    "rag_chunks": Table("document text chunks and their embeddings for chat evidence", S.ANYONE, R.BOOKS,
                        {"chunk_text": _DOC, "embedding": _DOC}, (Flow.LLM,), "the text is sent to the embedding endpoint"),
    "email_ingest_messages": Table("documents received by e-mail", S.ANYONE, R.OPERATIONAL, {"sender": _CT, "subject": _TXT}),
    "email_ingest_addresses": Table("the company's inbound address", S.MEMBER, R.ACCOUNT, {"created_by": _PSE}),
    # ── derived context ────────────────────────────────────────────────────
    "company_context_snapshots": Table("derived company picture", S.COMPANY, R.OPERATIONAL, {"context_json": _TXT}, (Flow.LLM,)),
    "company_semantic_snapshots": Table("derived metrics, drivers and brief", S.COMPANY, R.OPERATIONAL,
                                        {"brief_json": _TXT, "evidence_json": _TXT}, (Flow.LLM,)),
    "institutionalization_snapshots": Table("derived maturity score", S.COMPANY, R.OPERATIONAL, {"signals": _TXT, "recommendations": _TXT}),
    "cash_radar_snapshots": Table("derived cash radar", S.COUNTERPARTY, R.OPERATIONAL, {"snapshot_json": _TXT}),
    "agent_jobs": Table("queued agent jobs", S.ANYONE, R.OPERATIONAL, {"input_data": _TXT, "result_json": _TXT, "logs": _TXT, "error_message": _TXT},
                        (Flow.LLM,), "the input is the user's free text"),
    "agent_runs": Table("durable agent runs", S.ANYONE, R.OPERATIONAL, {"node_history": _TXT, "error": _TXT}),
    "agent_conflicts": Table("two agents' conflicting claims", S.ANYONE, R.OPERATIONAL,
                             {"claim_a": _TXT, "claim_b": _TXT, "resolution": _TXT}),
    "canonical_eng_signals": Table("engineering signals (GitHub)", S.ANYONE, R.OPERATIONAL, {"actor": _ID, "title": _TXT, "attributes": _TXT}),
    # ── notifications and outbound mail ────────────────────────────────────
    "outbox_messages": Table("every outward message: recipient, subject, body", S.ANYONE, R.OPERATIONAL,
                             {"recipient": _CT, "subject": _TXT, "body": _TXT, "last_error": _TXT},
                             (Flow.SMTP, Flow.SLACK, Flow.WHATSAPP)),
    "alert_preferences": Table("where alerts go", S.MEMBER, R.ACCOUNT,
                               {"email_recipients": _CT, "whatsapp_number": _CT, "slack_webhook_url": _CRED, "slack_channel": _TXT},
                               (Flow.SMTP, Flow.SLACK, Flow.WHATSAPP)),
    "alert_history": Table("alerts that fired", S.ANYONE, R.OPERATIONAL, {"message": _TXT, "acknowledged_by": _PSE}),
    "in_app_notifications": Table("notifications inside the product", S.ANYONE, R.OPERATIONAL, {"message": _TXT, "action": _TXT}),
    "proactive_alerts": Table("proactive KRI alerts", S.ANYONE, R.OPERATIONAL, {"title": _TXT, "body": _TXT, "metadata": _TXT}),
    "breach_notifications": Table("the company's breach record (KVKK Art. 12)", S.COMPANY, R.BOOKS, {"description": _TXT}),
    "compliance_certifications": Table("a signed compliance certification", S.MEMBER, R.BOOKS,
                                       {"certifier_name": _ID, "certifier_role": _TXT, "statements": _TXT}),
    "trigger_runs": Table("results of automation rules", S.ANYONE, R.OPERATIONAL, {"action_result": _TXT, "event_ref": _TXT}),
    # ── integrations ───────────────────────────────────────────────────────
    "connector_connections": Table("a connected external system", S.COMPANY, R.ACCOUNT,
                                   {"config_json": _TXT, "secret_enc": _CRED, "last_error": _TXT}),
    "erp_integrations": Table("a connected ERP", S.COMPANY, R.ACCOUNT,
                              {"access_token_enc": _CRED, "refresh_token_enc": _CRED, "config_enc": _CRED, "last_error": _TXT}),
    "erp_sync_logs": Table("ERP sync log", S.ANYONE, R.OPERATIONAL, {"error_message": _TXT}),
    "sync_runs": Table("connector sync runs", S.ANYONE, R.OPERATIONAL, {"error_message": _TXT}),
    "sync_schedules": Table("scheduled syncs", S.COMPANY, R.ACCOUNT, {"source_config": _TXT, "last_error": _TXT}),
    "trigger_definitions": Table("automation rules", S.COMPANY, R.ACCOUNT, {"condition": _TXT, "action_params": _TXT}),
    # ── logs and tokens ────────────────────────────────────────────────────
    "audit_logs": Table("who did what, when, from where", S.MEMBER, R.OPERATIONAL,
                        {"user_id": _PSE, "user_email": _CT, "request_body": _TXT, "ip_address": _NET, "user_agent": _NET, "reason": _TXT},
                        note="no organisation column: rows are linked to a company through the member"),
    "llm_call_logs": Table("one row per model call: task, model, tokens, cost, error (never the prompt)", S.ANYONE,
                           R.OPERATIONAL, {"error": _TXT}),
    "password_reset_tokens": Table("single-use reset links", S.MEMBER, R.OPERATIONAL, {"user_id": _PSE, "token_hash": _CRED}),
    "email_verification_tokens": Table("single-use verification links", S.MEMBER, R.OPERATIONAL, {"user_id": _PSE, "token_hash": _CRED}),
    "org_erasure_requests": Table("the erasure handshake", S.MEMBER, R.PROOF, {"requested_by_user_id": _PSE},
                                  note="raw ids are nulled when the erasure runs; hashes remain"),
    "org_erasure_records": Table("hash-chained proof that an erasure ran", S.COMPANY, R.PROOF, {}, note="hashes and counts only"),
}

NO_PERSONAL_DATA: dict[str, str] = {
    "alert_rules": "threshold rules: a metric, an operator, a number and a label the user types",
    "donem_kilitleri": "closed accounting periods: a period and a date",
}

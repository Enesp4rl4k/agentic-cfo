# Kisisel veri haritasi (uretilmis)

> GENERATED from `backend/app/services/privacy/registry*.py` by `python -m app.services.privacy.inventory_doc`.
> Do not edit by hand: `tests/test_privacy_registry.py` fails when this file is stale. It records what the CODE
> does. Legal bases, retention periods and the cross-border position are not decided here:
> see [avukata-sorular.md](avukata-sorular.md). PR #68's `veri-envanteri.md` is the hand-written, line-referenced
> companion; [mismatches](veri-envanteri-farklar.md) lists where the two disagree.

## Tables

66 tables hold or may hold personal data (69 tables exist).

| Table | Whose | Purpose | Columns (category) | Retention class | Retention job | On organisation erasure | Third parties |
|---|---|---|---|---|---|---|---|
| `agent_conflicts` | anyone | two agents' conflicting claims | `claim_a` (free_text), `claim_b` (free_text), `resolution` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `agent_jobs` | anyone | queued agent jobs | `error_message` (free_text), `input_data` (free_text), `logs` (free_text), `result_json` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | llm_provider |
| `agent_runs` | anyone | durable agent runs | `error` (free_text), `node_history` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `alert_history` | anyone | alerts that fired | `acknowledged_by` (pseudonym), `message` (free_text) | operational | `alert_history` (dry_run_default), `erasure_leftovers` (enforced) | deleted | - |
| `alert_preferences` | member | where alerts go | `email_recipients` (contact), `slack_channel` (free_text), `slack_webhook_url` (credential), `whatsapp_number` (contact) | account | `erasure_leftovers` (enforced) | deleted | smtp_provider, slack_webhook, whatsapp_twilio |
| `analysis_jobs` | anyone | an uploaded file and its processing | `error_message` (free_text), `file_path` (free_text), `filename` (free_text), `locked_by` (pseudonym), `logs` (free_text), `result_metadata` (free_text), `smmm_client_id` (pseudonym), `user_id` (pseudonym) | books | `uploads` (dry_run_default), `erasure_leftovers` (enforced) | kept, columns scrubbed | - |
| `anomalies` | counterparty | detected anomalies | `description` (free_text), `evidence` (free_text), `title` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | llm_provider |
| `audit_logs` | member | who did what, when, from where | `ip_address` (network), `reason` (free_text), `request_body` (free_text), `user_agent` (network), `user_email` (contact), `user_id` (pseudonym) | operational | `audit_ip` (dry_run_default) | kept, columns scrubbed | - |
| `authority_policies` | company | who may approve what | `note` (free_text) | account | `erasure_leftovers` (enforced) | deleted | - |
| `breach_notifications` | company | the company's breach record (KVKK Art. 12) | `description` (free_text) | books | `erasure_leftovers` (enforced) | deleted | - |
| `canonical_eng_signals` | anyone | engineering signals (GitHub) | `actor` (identity), `attributes` (free_text), `title` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `canonical_transactions` | counterparty | the single ledger | `counterparty` (identity), `description` (free_text) | books | `erasure_leftovers` (enforced) | kept, columns scrubbed | llm_provider |
| `cash_radar_snapshots` | counterparty | derived cash radar | `snapshot_json` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `category_overrides` | member | a person's single-row category corrections | - | account | `erasure_leftovers` (enforced) | deleted | - |
| `category_rules` | counterparty | category rules by vendor | `keyword_match` (free_text), `vendor_match` (identity) | account | `erasure_leftovers` (enforced) | deleted | - |
| `company_context_snapshots` | company | derived company picture | `context_json` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | llm_provider |
| `company_semantic_snapshots` | company | derived metrics, drivers and brief | `brief_json` (free_text), `evidence_json` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | llm_provider |
| `compliance_certifications` | member | a signed compliance certification | `certifier_name` (identity), `certifier_role` (free_text), `statements` (free_text) | books | `erasure_leftovers` (enforced) | deleted | - |
| `connector_connections` | company | a connected external system | `config_json` (free_text), `last_error` (free_text), `secret_enc` (credential) | account | `erasure_leftovers` (enforced) | deleted | - |
| `counterparty_aliases` | counterparty | two spellings declared one supplier | `alias_name` (identity), `alias_token` (pseudonym), `canonical_name` (identity), `canonical_token` (pseudonym), `created_by` (pseudonym), `revoked_by` (pseudonym) | account | `erasure_leftovers` (enforced) | deleted | - |
| `data_exports` | anyone | a company-wide export bundle (the file holds the whole company's data) | `file_path` (free_text), `requested_by` (pseudonym) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `data_sources` | anyone | an additional uploaded file | `file_path` (free_text), `filename` (free_text), `label` (free_text) | books | `erasure_leftovers` (enforced) | deleted | - |
| `decision_logs` | member | the decision journal | `created_by` (pseudonym), `outcome_note` (free_text), `rationale` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `decisions` | member | who decided what (append-only decision record) | `after` (free_text), `before` (free_text), `decided_by` (pseudonym), `reason` (free_text) | books | `erasure_leftovers` (enforced) | kept, columns scrubbed | - |
| `defensibility_packets` | counterparty | a sealed accountant defensibility packet | `payload` (free_text), `smmm_statement` (free_text), `summary` (free_text) | books | `erasure_leftovers` (enforced) | deleted | - |
| `direction_mappings` | member | standing answers about a statement's columns | `answer` (free_text), `created_by` (pseudonym), `flagged_note` (free_text), `reason` (free_text), `revoked_by` (pseudonym) | account | `erasure_leftovers` (enforced) | deleted | - |
| `email_ingest_addresses` | member | the company's inbound address | `created_by` (pseudonym) | account | `erasure_leftovers` (enforced) | deleted | - |
| `email_ingest_messages` | anyone | documents received by e-mail | `sender` (contact), `subject` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `email_verification_tokens` | member | single-use verification links | `token_hash` (credential), `user_id` (pseudonym) | operational | `tokens` (dry_run_default) | deleted | - |
| `erp_integrations` | company | a connected ERP | `access_token_enc` (credential), `config_enc` (credential), `last_error` (free_text), `refresh_token_enc` (credential) | account | `erasure_leftovers` (enforced) | deleted | - |
| `erp_sync_logs` | anyone | ERP sync log | `error_message` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `held_transactions` | counterparty | rows the system would not book alone | `payload` (free_text), `resolved_by` (pseudonym) | books | `erasure_leftovers` (enforced) | deleted | - |
| `in_app_notifications` | anyone | notifications inside the product | `action` (free_text), `message` (free_text) | operational | `notifications` (dry_run_default), `erasure_leftovers` (enforced) | deleted | - |
| `institutionalization_snapshots` | company | derived maturity score | `recommendations` (free_text), `signals` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `journal_entries` | counterparty | double-entry journal | `aciklama` (free_text), `onay_neden` (free_text) | books | `erasure_leftovers` (enforced) | kept, columns scrubbed | - |
| `journal_lines` | counterparty | journal lines | `aciklama` (free_text) | books | `erasure_leftovers` (enforced) | kept, columns scrubbed | - |
| `llm_call_logs` | anyone | one row per model call: task, model, tokens, cost, data mode, bytes sent, placeholder counts, error (the exception type and a fixed code only, never its message, never the prompt) | `error` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `open_item_matches` | member | invoice-to-payment matches | `decided_by` (pseudonym) | books | `erasure_leftovers` (enforced) | kept, columns scrubbed | - |
| `open_items` | counterparty | receivables and payables | `counterparty` (identity), `description` (free_text), `payment_note` (free_text) | books | `erasure_leftovers` (enforced) | kept, columns scrubbed | llm_provider |
| `org_erasure_records` | company | hash-chained proof that an erasure ran | - | proof | - (no retention job: kept until erasure) | kept (proof, no personal data) | - |
| `org_erasure_requests` | member | the erasure handshake | `requested_by_user_id` (pseudonym) | proof | - (no retention job: kept until erasure) | kept (proof, no personal data) | - |
| `org_invites` | member | invitation of a person to a company | `email` (contact), `token` (credential) | operational | `invitations` (dry_run_default), `erasure_leftovers` (enforced) | deleted | smtp_provider |
| `org_memberships` | member | who belongs to which company, in which role | `user_id` (pseudonym) | account | `erasure_leftovers` (enforced) | deleted | - |
| `organizations` | company | the customer company and its billing | `base_currency_confirmed_by` (pseudonym), `description` (free_text), `ip_whitelist` (network), `legal_title` (identity), `logo_url` (free_text), `materiality_applied` (pseudonym), `name` (identity), `size_profile_set_by` (pseudonym), `slug` (identity), `stripe_customer_id` (pseudonym), `stripe_subscription_id` (pseudonym), `vkn` (tax_id) | account | - (no retention job: kept until erasure) | kept, columns scrubbed | llm_provider, stripe |
| `outbox_messages` | anyone | every outward message: recipient, subject, body | `body` (free_text), `last_error` (free_text), `recipient` (contact), `subject` (free_text) | operational | `outbox_bodies` (dry_run_default), `erasure_leftovers` (enforced) | deleted | smtp_provider, slack_webhook, whatsapp_twilio |
| `password_reset_tokens` | member | single-use reset links | `token_hash` (credential), `user_id` (pseudonym) | operational | `tokens` (dry_run_default) | deleted | - |
| `payment_plan_changes` | member | proposed changes to a payment plan | `decided_by` (pseudonym), `decision_note` (free_text), `request_note` (free_text), `requested_by` (pseudonym) | books | `erasure_leftovers` (enforced) | deleted | - |
| `pilot_invites` | member | pilot access codes | `company_name` (identity), `email` (contact), `issued_by` (pseudonym), `note` (free_text), `token_hash` (credential), `used_by_user_id` (pseudonym) | operational | - (no retention job: kept until erasure) | deleted | - |
| `proactive_alerts` | anyone | proactive KRI alerts | `body` (free_text), `metadata` (free_text), `title` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `rag_chunks` | anyone | document text chunks and their embeddings for chat evidence | `chunk_text` (document), `embedding` (document) | books | `uploads` (dry_run_default), `erasure_leftovers` (enforced) | deleted | llm_provider |
| `related_parties` | counterparty | related parties of the company | `created_by` (pseudonym), `name` (identity), `normalized_name` (identity), `note` (free_text), `tax_id` (tax_id) | account | `erasure_leftovers` (enforced) | deleted | - |
| `reports` | counterparty | generated reports (files and JSON) | `data` (free_text), `file_path` (free_text) | books | `erasure_leftovers` (enforced) | deleted | - |
| `retention_runs` | company | one row per run of the retention job: counts only | - | proof | - (no retention job: kept until erasure) | kept (proof, no personal data) | - |
| `scheduled_job_runs` | company | one claim per scheduled job, company and period (idempotency ledger) | `last_error` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `smmm_hesap_kurallari` | counterparty | an accountant's account-code rules | `anahtar` (identity) | books | `erasure_leftovers` (enforced) | deleted | - |
| `smmm_muhasebeci` | accountant | an accountant's portal profile | `firma_adi` (identity), `il` (free_text), `oda_no` (tax_id), `telefon` (contact), `unvan` (identity), `vergi_no` (tax_id) | account | - (no retention job: kept until erasure) | deleted | - |
| `smmm_musteri_kayit` | counterparty | an accountant's client list | `firma_adi` (identity), `il` (free_text), `notlar` (free_text), `vergi_no` (tax_id) | account | - (no retention job: kept until erasure) | deleted | - |
| `smmm_onay_kayitlari` | counterparty | accountant approvals and corrections | `created_by_user_id` (pseudonym), `duzeltme_aciklama` (free_text), `onay_neden` (free_text), `onay_notu` (free_text), `onaylayan_user_id` (pseudonym), `orijinal_kayit` (free_text), `tx_description` (free_text) | books | `erasure_leftovers` (enforced) | kept, columns scrubbed | - |
| `sync_runs` | anyone | connector sync runs | `error_message` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `sync_schedules` | company | scheduled syncs | `last_error` (free_text), `source_config` (free_text) | account | `erasure_leftovers` (enforced) | deleted | - |
| `terms_acceptances` | member | which notice and terms version a person accepted, and when | `user_id` (pseudonym) | account | - (no retention job: kept until erasure) | deleted | - |
| `transactions` | counterparty | income and expense lines read from documents | `counterparty` (identity), `description` (free_text), `payment_note` (free_text), `raw_text` (document), `vendor` (identity) | books | `uploads` (dry_run_default), `erasure_leftovers` (enforced) | kept, columns scrubbed | llm_provider |
| `trigger_definitions` | company | automation rules | `action_params` (free_text), `condition` (free_text) | account | `erasure_leftovers` (enforced) | deleted | - |
| `trigger_runs` | anyone | results of automation rules | `action_result` (free_text), `event_ref` (free_text) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `user_feedback` | member | in-product feedback | `biggest_benefit` (free_text), `biggest_gap` (free_text), `comment` (free_text), `page_context` (free_text), `user_id` (pseudonym) | operational | `erasure_leftovers` (enforced) | deleted | - |
| `users` | member | accounts and sign-in | `api_key` (credential), `email` (contact), `full_name` (identity), `hashed_password` (credential), `sso_id` (pseudonym) | account | - (no retention job: kept until erasure) | deleted | sso_provider |

## Stores outside the tables

| Store | Holds | Where | Retention class | Lifetime | In effect | Erased by |
|---|---|---|---|---|---|---|
| `uploads` | the uploaded file itself (PDF, XLSX, CSV, XML): statements, invoices, anything in them | <STORAGE_LOCAL_PATH>/uploads/<job_id>/ and <STORAGE_LOCAL_PATH>/<job_id>_<name> (demo upload) | books | kept until erasure or the raw-file retention job (default: keep) | dry_run_default: the raw-file purge (`uploads` below; RETENTION_UPLOAD_DAYS, default 0 = keep) only counts while RETENTION_DRY_RUN=true | org_erasure.remove_org_files |
| `report_files` | generated report files and PDFs | <STORAGE_LOCAL_PATH>/reports/<job_id>/ | books | kept until erasure | not_applicable: no retention period: part of the books, kept until erasure | org_erasure.remove_org_files |
| `board_decks` | board-deck PDFs | <STORAGE_LOCAL_PATH>/board_decks/<job_id>.pdf | books | kept until erasure | not_applicable: no retention period: part of the books, kept until erasure | org_erasure.remove_org_files |
| `exports` | a company's data-export bundle (ZIP) and a member's personal export | <STORAGE_LOCAL_PATH>/exports/<export_id>.zip | operational | deleted when the download window closes (DATA_EXPORT_TTL_HOURS) | enforced: the hourly export expiry deletes the file when the window closes; never gated by RETENTION_DRY_RUN | org_erasure.remove_org_files and the export purge |
| `chat_history` | the user's questions and the model's answers | Redis conv:<user>:<session> | ephemeral | 7 days, sliding | not_applicable: a Redis time-to-live, no job: the key expires by itself | privacy.ephemeral |
| `redis_derived` | company context, semantic snapshots, briefings, temporal events, analytics cache, CEO job results, alert acknowledgements | Redis company_context:, semantic:, morning_brief:, monday_briefing:, temporal:, cache:..., ceo:<job>, ack:<job>:... | ephemeral | 30 minutes to 7 days | not_applicable: Redis time-to-lives, no job: the keys expire by themselves | privacy.ephemeral |
| `agent_memory` | one narrative and summary per agent run per organisation | table agent_memory_episodes (PostgreSQL) / agent_memory (SQLite), outside the ORM metadata | operational | no expiry before this work | not_applicable: no retention period is set: the agents read it back (episodic memory); erased with the organisation, and no row is written for an organisation being erased (privacy.tombstone) | privacy.ephemeral |
| `agent_checkpoints` | the state of a CFO pipeline run after each step: the statement's rows, the figures and the narrative text, with the names the masking replaced RESTORED (as shown to the user), so real counterparty and company names. Nothing reads it back (no resume); a run without an organisation is not checkpointed | tables checkpoints, checkpoint_blobs, checkpoint_writes (PostgreSQL, created by the langgraph library, outside the ORM metadata; thread id `<org_id>:<job_id>:<run_id>`, one per run). Development with SQLite: the file CHECKPOINT_SQLITE_PATH, which erasure does not touch | operational | 3 days after the run's last step (RETENTION_CHECKPOINT_DAYS); a thread not namespaced by an organisation, or of an organisation erased or gone, at the next retention run | enforced: nothing reads a checkpoint back (no resume, no inspection tool), so there is no report to review first: the retention job deletes them whatever RETENTION_DRY_RUN says | privacy.ephemeral inside the erase transaction (the organisation's threads, and un-namespaced threads of its jobs written before 2026-11-27), the saver refusing every write once the erasure is claimed (privacy.tombstone), the erasure's final sweep and the retention job |
| `llm_provider_side` | prompts and responses as the model provider keeps them | the provider | operational | set by the provider, outside our control | not_applicable: outside our reach: the provider's own retention (Q1) | cannot be erased by us: lawyer question Q1 |
| `application_logs` | log lines: request paths, error messages that can name a counterparty | container stdout (docker log driver) | operational | set by the log driver; not defined in this repository | not_applicable: the operator's log driver rotates them, not this code | cannot be erased per organisation |
| `sentry` | error events (keys scrubbed, `send_default_pii=False`) | Sentry, only when SENTRY_DSN is set | operational | set by the Sentry project | not_applicable: the Sentry project's retention, not this code | cannot be erased by us |
| `backups` | a copy of everything above that is in the database or the volume | the operator's database backups and volume snapshots | operational | the backup rotation (BACKUP_RETENTION_DAYS of the operator) | not_applicable: the operator's backup rotation, not this code | NOT purged retroactively: an erased organisation reappears only if a backup is restored; the restore runbook must re-run the erasure records (see docs/kvkk/yedek-ve-silme.md) |

## Retention: in effect or not

`enforced`: the retention job deletes it whatever `RETENTION_DRY_RUN` says (nothing reads it, or it is erasure rather
than retention). `dry_run_default`: counted only while `RETENTION_DRY_RUN=true`, the default; deleted once the operator
sets it to false after reviewing the first report (docs/ops/first-deploy-checklist.md). Until then that period is NOT
in effect. `not_applicable`: no retention job (kept until erasure, a cache time-to-live, or outside our reach).
The job reads this table (`retention.ENFORCED_ALWAYS`); `tests/test_privacy_registry.py` ties both to the code.

| Purge | What | Tables | Period | In effect | Why |
|---|---|---|---|---|---|
| `uploads` | the raw file (uploads store), raw text and text chunks of a processed upload (the ledger rows stay) | `analysis_jobs`, `transactions`, `rag_chunks` | RETENTION_UPLOAD_DAYS (default 0 = keep) | dry_run_default | the source document of the books and the chat evidence read from it; deleting it is irreversible and something still reads it, so the operator reviews the first dry-run report before RETENTION_DRY_RUN=false |
| `outbox_bodies` | the body of a delivered outward message (recipient, status and times stay) | `outbox_messages` | RETENTION_OUTBOX_BODY_DAYS (default 90) | dry_run_default | the company's record of what it sent; deleting it is irreversible and something still reads it, so the operator reviews the first dry-run report before RETENTION_DRY_RUN=false |
| `notifications` | in-app notifications | `in_app_notifications` | RETENTION_NOTIFICATION_DAYS (default 180) | dry_run_default | listed in the product's notification panel; deleting it is irreversible and something still reads it, so the operator reviews the first dry-run report before RETENTION_DRY_RUN=false |
| `alert_history` | fired-alert history | `alert_history` | RETENTION_ALERT_HISTORY_DAYS (default 365) | dry_run_default | listed in the alert history; deleting it is irreversible and something still reads it, so the operator reviews the first dry-run report before RETENTION_DRY_RUN=false |
| `tokens` | password-reset and e-mail-verification tokens past their expiry | `password_reset_tokens`, `email_verification_tokens` | RETENTION_TOKEN_DAYS after expiry (default 30) | dry_run_default | an old link is still answered `expired` rather than `invalid`; deleting it is irreversible and something still reads it, so the operator reviews the first dry-run report before RETENTION_DRY_RUN=false |
| `invitations` | spent or expired invitations | `org_invites` | RETENTION_TOKEN_DAYS (default 30) | dry_run_default | an old invitation link is still answered `expired` / `already accepted`; deleting it is irreversible and something still reads it, so the operator reviews the first dry-run report before RETENTION_DRY_RUN=false |
| `audit_ip` | audit-log IP address truncated (/24, /48) and browser string removed; the row stays | `audit_logs` | RETENTION_AUDIT_IP_DAYS (default 365) | dry_run_default | the security audit log shows them; deleting it is irreversible and something still reads it, so the operator reviews the first dry-run report before RETENTION_DRY_RUN=false |
| `checkpoints` | LangGraph checkpoint threads whose newest step is older than the period | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` | RETENTION_CHECKPOINT_DAYS after the last step (default 3; 0 keeps them), wall clock | enforced | nothing reads a checkpoint back (no resume, no inspection tool) |
| `checkpoints_unscoped` | checkpoint threads not namespaced by an organisation (written before 2026-11-27) | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` | at once, any age | enforced | orphans: no reader, and no organisation's erasure can match them |
| `checkpoints_orphaned` | checkpoint threads of an organisation that is erased or no longer exists | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` | at once, any age | enforced | erasure, not retention: the company is gone and nothing reads them |
| `erasure_leftovers` | whatever was written for an organisation after its erasure committed (organisations erased in the last 30 days): the erasure's OWN plan run again, so every organisation-scoped table (org_erasure.derive_scope, listed in the Tables section under this key), the checkpoints, the agent memory, the files and the Redis keys | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `agent_memory_episodes` | at once (organisations erased in the last ERASURE_SWEEP_DAYS = 30 days) | enforced | erasure, not retention: the company is erased. Writes are refused under the organisation's lock (privacy.write_guard, privacy.tombstone); this removes what got past, with no second list of tables |

## Third parties

### LLM provider (default DeepSeek, an OpenAI-compatible endpoint set by LLM_BASE_URL)

- Receives: by LLM_DATA_MODE (default `masked`): the figures, dates and currencies as they are in the books; counterparty, vendor, company, member and accountant names the books hold, and IBAN, TCKN, VKN, card, phone and e-mail patterns, replaced by placeholders and restored in the reply; transaction descriptions, uploaded-document text (up to 8,000 characters per extraction call, and 1,800-character chunks for embeddings) and chat questions with their history with only those replacements, so free text can still hold personal data that neither the patterns nor the known names catch. `raw` sends all of it as it is; `off` sends nothing.
- Masked before sending: yes.
- Code: app/platform/model_gateway.py, app/platform/embedding_gateway.py, app/platform/llm_egress/ (docs/kvkk/yapay-zeka-veri-akisi.md says exactly what leaves in each mode).
- Off / on: LLM_DATA_MODE=off|masked|raw, per company by its owner (PUT /privacy/ai-data-mode, with a decision record); LLM_DOCUMENT_TEXT=never sends no document text; no key, or a `llm-placeholder-*` key, makes no network call.
- Open question: Q1/Q15: cross-border transfer basis (KVKK Art. 9) for the provider chosen, and whether masking, document-text strictness or no AI at all must be required. The options exist; which one is lawful is not decided here.
- Registry entries that can reach it: `agent_jobs`, `agent_memory`, `anomalies`, `canonical_transactions`, `chat_history`, `company_context_snapshots`, `company_semantic_snapshots`, `llm_provider_side`, `open_items`, `organizations`, `rag_chunks`, `redis_derived`, `transactions`, `uploads`.

### SMTP provider (default smtp.gmail.com)

- Receives: recipient address, subject and body of every outbox e-mail: alerts, briefings, invitations, reset links.
- Masked before sending: NO.
- Code: app/services/outbox_transport.py.
- Off / on: SMTP settings; unset means nothing is sent.
- Open question: Q1: provider location; whether a Turkish SMTP provider is required.
- Registry entries that can reach it: `alert_preferences`, `org_invites`, `outbox_messages`.

### Slack / Teams / custom webhook (only when the company configures one)

- Receives: alert text, which may name a counterparty.
- Masked before sending: NO.
- Code: app/services/outbox_transport.py.
- Off / on: a webhook URL set by the company in its alert preferences.
- Open question: Q1: processor terms; the customer's own choice.
- Registry entries that can reach it: `alert_preferences`, `outbox_messages`.

### WhatsApp (Meta) / Twilio (only when the company configures a number)

- Receives: the recipient's phone number and the alert text.
- Masked before sending: NO.
- Code: app/services/notification_service.py.
- Off / on: a WhatsApp number in alert preferences plus provider credentials.
- Open question: Q1: processor terms; the customer's own choice.
- Registry entries that can reach it: `alert_preferences`, `outbox_messages`.

### Stripe (billing)

- Receives: organisation name, billing contact, customer and subscription ids.
- Masked before sending: yes.
- Code: app/services/stripe_billing.py.
- Off / on: STRIPE_* settings.
- Open question: Q1: cross-border basis; Stripe's own controller role.
- Registry entries that can reach it: `organizations`.

### Microsoft / Google / GitHub sign-in (only when a person signs in with it)

- Receives: the provider authenticates the person and returns their id, e-mail and name.
- Masked before sending: yes.
- Code: app/services/sso.py.
- Off / on: SSO_* settings.
- Open question: Q1: none beyond the provider's own role.
- Registry entries that can reach it: `users`.

### Sentry error tracking (off unless SENTRY_DSN is set)

- Receives: error events with keys scrubbed; log lines at ERROR level may name a counterparty.
- Masked before sending: yes.
- Code: app/services/sentry_monitoring.py.
- Off / on: SENTRY_DSN; unset means no events leave.
- Open question: Q1: EU region and a processing agreement before it is turned on.
- Registry entries that can reach it: `sentry`.

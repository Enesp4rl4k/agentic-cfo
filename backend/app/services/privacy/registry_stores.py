"""The non-table half of the personal-data registry: files, caches, memory, logs, backups; and what the retention
job purges, with whether each purge is in effect (`PURGES`)."""
from __future__ import annotations

from app.services.privacy.registry import Enforcement, Flow, Purge, Retention, Store, Subject

S = Subject
R = Retention
E = Enforcement

STORES: tuple[Store, ...] = (
    Store("uploads", "the uploaded file itself (PDF, XLSX, CSV, XML): statements, invoices, anything in them",
          "<STORAGE_LOCAL_PATH>/uploads/<job_id>/ and <STORAGE_LOCAL_PATH>/<job_id>_<name> (demo upload)",
          S.ANYONE, R.BOOKS, "kept until erasure or the raw-file retention job (default: keep)",
          "org_erasure.remove_org_files", (Flow.LLM,), E.DRY_RUN_DEFAULT,
          "the raw-file purge (`uploads` below; RETENTION_UPLOAD_DAYS, default 0 = keep) only counts while "
          "RETENTION_DRY_RUN=true"),
    Store("report_files", "generated report files and PDFs", "<STORAGE_LOCAL_PATH>/reports/<job_id>/",
          S.COUNTERPARTY, R.BOOKS, "kept until erasure", "org_erasure.remove_org_files",
          enforcement=E.NOT_APPLICABLE, enforcement_why="no retention period: part of the books, kept until erasure"),
    Store("board_decks", "board-deck PDFs", "<STORAGE_LOCAL_PATH>/board_decks/<job_id>.pdf",
          S.COUNTERPARTY, R.BOOKS, "kept until erasure", "org_erasure.remove_org_files",
          enforcement=E.NOT_APPLICABLE, enforcement_why="no retention period: part of the books, kept until erasure"),
    Store("exports", "a company's data-export bundle (ZIP) and a member's personal export",
          "<STORAGE_LOCAL_PATH>/exports/<export_id>.zip", S.ANYONE, R.OPERATIONAL,
          "deleted when the download window closes (DATA_EXPORT_TTL_HOURS)",
          "org_erasure.remove_org_files and the export purge", enforcement=E.ENFORCED,
          enforcement_why="the hourly export expiry deletes the file when the window closes; never gated by "
          "RETENTION_DRY_RUN"),
    Store("chat_history", "the user's questions and the model's answers", "Redis conv:<user>:<session>",
          S.ANYONE, R.EPHEMERAL, "7 days, sliding", "privacy.ephemeral", (Flow.LLM,), E.NOT_APPLICABLE,
          "a Redis time-to-live, no job: the key expires by itself"),
    Store("redis_derived", "company context, semantic snapshots, briefings, temporal events, analytics cache, "
          "CEO job results, alert acknowledgements", "Redis company_context:, semantic:, morning_brief:, "
          "monday_briefing:, temporal:, cache:..., ceo:<job>, ack:<job>:...", S.COUNTERPARTY, R.EPHEMERAL,
          "30 minutes to 7 days", "privacy.ephemeral", (Flow.LLM,), E.NOT_APPLICABLE,
          "Redis time-to-lives, no job: the keys expire by themselves"),
    Store("agent_memory", "one narrative and summary per agent run per organisation",
          "table agent_memory_episodes (PostgreSQL) / agent_memory (SQLite), outside the ORM metadata",
          S.COUNTERPARTY, R.OPERATIONAL, "no expiry before this work", "privacy.ephemeral", (Flow.LLM,),
          E.NOT_APPLICABLE, "no retention period is set: the agents read it back (episodic memory); erased with the "
          "organisation, and no row is written for an organisation being erased (privacy.tombstone)"),
    Store("agent_checkpoints", "the state of a CFO pipeline run after each step: the statement's rows, the figures "
          "and the narrative text, with the names the masking replaced RESTORED (as shown to the user), so real "
          "counterparty and company names. Nothing reads it back (no resume); a run without an organisation is "
          "not checkpointed",
          "tables checkpoints, checkpoint_blobs, checkpoint_writes (PostgreSQL, created by the langgraph library, "
          "outside the ORM metadata; thread id `<org_id>:<job_id>:<run_id>`, one per run). Development with SQLite: "
          "the file CHECKPOINT_SQLITE_PATH, which erasure does not touch",
          S.COUNTERPARTY, R.OPERATIONAL, "3 days after the run's last step (RETENTION_CHECKPOINT_DAYS); a thread "
          "not namespaced by an organisation, or of an organisation erased or gone, at the next retention run",
          "privacy.ephemeral inside the erase transaction (the organisation's threads, and un-namespaced threads of "
          "its jobs written before 2026-11-27), the saver refusing every write once the erasure is claimed "
          "(privacy.tombstone), the erasure's final sweep and the retention job",
          enforcement=E.ENFORCED,
          enforcement_why="nothing reads a checkpoint back (no resume, no inspection tool), so there is no report "
          "to review first: the retention job deletes them whatever RETENTION_DRY_RUN says"),
    Store("llm_provider_side", "prompts and responses as the model provider keeps them", "the provider",
          S.ANYONE, R.OPERATIONAL, "set by the provider, outside our control",
          "cannot be erased by us: lawyer question Q1", (Flow.LLM,), E.NOT_APPLICABLE,
          "outside our reach: the provider's own retention (Q1)"),
    Store("application_logs", "log lines: request paths, error messages that can name a counterparty",
          "container stdout (docker log driver)", S.ANYONE, R.OPERATIONAL,
          "set by the log driver; not defined in this repository", "cannot be erased per organisation",
          enforcement=E.NOT_APPLICABLE, enforcement_why="the operator's log driver rotates them, not this code"),
    Store("sentry", "error events (keys scrubbed, `send_default_pii=False`)", "Sentry, only when SENTRY_DSN is set",
          S.ANYONE, R.OPERATIONAL, "set by the Sentry project", "cannot be erased by us", (Flow.SENTRY,),
          E.NOT_APPLICABLE, "the Sentry project's retention, not this code"),
    Store("backups", "a copy of everything above that is in the database or the volume",
          "the operator's database backups and volume snapshots", S.ANYONE, R.OPERATIONAL,
          "the backup rotation (BACKUP_RETENTION_DAYS of the operator)",
          "NOT purged retroactively: an erased organisation reappears only if a backup is restored; "
          "the restore runbook must re-run the erasure records (see docs/kvkk/yedek-ve-silme.md)",
          enforcement=E.NOT_APPLICABLE, enforcement_why="the operator's backup rotation, not this code"),
)

CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")  # PostgreSQL, the library's

_REVIEW = ("deleting it is irreversible and something still reads it, so the operator reviews the first dry-run "
           "report before RETENTION_DRY_RUN=false")

# Every key the retention job reports (`retention.run_retention` counts), and whether it is in effect today.
PURGES: dict[str, Purge] = {
    "uploads": Purge("the raw file (uploads store), raw text and text chunks of a processed upload (the ledger rows stay)",
                     ("analysis_jobs", "transactions", "rag_chunks"),
                     "RETENTION_UPLOAD_DAYS (default 0 = keep)", E.DRY_RUN_DEFAULT,
                     "the source document of the books and the chat evidence read from it; " + _REVIEW),
    "outbox_bodies": Purge("the body of a delivered outward message (recipient, status and times stay)",
                           ("outbox_messages",), "RETENTION_OUTBOX_BODY_DAYS (default 90)", E.DRY_RUN_DEFAULT,
                           "the company's record of what it sent; " + _REVIEW),
    "notifications": Purge("in-app notifications", ("in_app_notifications",), "RETENTION_NOTIFICATION_DAYS (default 180)",
                           E.DRY_RUN_DEFAULT, "listed in the product's notification panel; " + _REVIEW),
    "alert_history": Purge("fired-alert history", ("alert_history",), "RETENTION_ALERT_HISTORY_DAYS (default 365)",
                           E.DRY_RUN_DEFAULT, "listed in the alert history; " + _REVIEW),
    "tokens": Purge("password-reset and e-mail-verification tokens past their expiry",
                    ("password_reset_tokens", "email_verification_tokens"), "RETENTION_TOKEN_DAYS after expiry (default 30)",
                    E.DRY_RUN_DEFAULT, "an old link is still answered `expired` rather than `invalid`; " + _REVIEW),
    "invitations": Purge("spent or expired invitations", ("org_invites",), "RETENTION_TOKEN_DAYS (default 30)",
                         E.DRY_RUN_DEFAULT, "an old invitation link is still answered `expired` / `already accepted`; "
                         + _REVIEW),
    "audit_ip": Purge("audit-log IP address truncated (/24, /48) and browser string removed; the row stays",
                      ("audit_logs",), "RETENTION_AUDIT_IP_DAYS (default 365)",
                      E.DRY_RUN_DEFAULT, "the security audit log shows them; " + _REVIEW),
    "checkpoints": Purge("LangGraph checkpoint threads whose newest step is older than the period",
                         CHECKPOINT_TABLES,
                         "RETENTION_CHECKPOINT_DAYS after the last step (default 3; 0 keeps them), wall clock",
                         E.ENFORCED, "nothing reads a checkpoint back (no resume, no inspection tool)"),
    "checkpoints_unscoped": Purge("checkpoint threads not namespaced by an organisation (written before 2026-11-27)",
                                  CHECKPOINT_TABLES, "at once, any age",
                                  E.ENFORCED, "orphans: no reader, and no organisation's erasure can match them"),
    "checkpoints_orphaned": Purge("checkpoint threads of an organisation that is erased or no longer exists",
                                  CHECKPOINT_TABLES, "at once, any age",
                                  E.ENFORCED, "erasure, not retention: the company is gone and nothing reads them"),
    "erasure_leftovers": Purge("what a run in flight wrote for an organisation erased in the last 30 days: "
                               "checkpoints, agent memory, model-call log and run-ledger rows",
                               (*CHECKPOINT_TABLES, "agent_memory_episodes", "llm_call_logs", "agent_runs"),
                               "at once (organisations erased in the last ERASURE_SWEEP_DAYS = 30 days)", E.ENFORCED,
                               "erasure, not retention: the company is erased; refused at write time "
                               "(privacy.tombstone), swept again here"),
}

"""The non-table half of the personal-data registry: files, caches, memory, logs, backups."""
from __future__ import annotations

from app.services.privacy.registry import Flow, Retention, Store, Subject

S = Subject
R = Retention

STORES: tuple[Store, ...] = (
    Store("uploads", "the uploaded file itself (PDF, XLSX, CSV, XML): statements, invoices, anything in them",
          "<STORAGE_LOCAL_PATH>/uploads/<job_id>/ and <STORAGE_LOCAL_PATH>/<job_id>_<name> (demo upload)",
          S.ANYONE, R.BOOKS, "kept until erasure or the raw-file retention job (default: keep)",
          "org_erasure.remove_org_files", (Flow.LLM,)),
    Store("report_files", "generated report files and PDFs", "<STORAGE_LOCAL_PATH>/reports/<job_id>/",
          S.COUNTERPARTY, R.BOOKS, "kept until erasure", "org_erasure.remove_org_files"),
    Store("board_decks", "board-deck PDFs", "<STORAGE_LOCAL_PATH>/board_decks/<job_id>.pdf",
          S.COUNTERPARTY, R.BOOKS, "kept until erasure", "org_erasure.remove_org_files"),
    Store("exports", "a company's data-export bundle (ZIP) and a member's personal export",
          "<STORAGE_LOCAL_PATH>/exports/<export_id>.zip", S.ANYONE, R.OPERATIONAL,
          "deleted when the download window closes (DATA_EXPORT_TTL_HOURS)",
          "org_erasure.remove_org_files and the export purge"),
    Store("chat_history", "the user's questions and the model's answers", "Redis conv:<user>:<session>",
          S.ANYONE, R.EPHEMERAL, "7 days, sliding", "privacy.ephemeral", (Flow.LLM,)),
    Store("redis_derived", "company context, semantic snapshots, briefings, temporal events, analytics cache, "
          "CEO job results, alert acknowledgements", "Redis company_context:, semantic:, morning_brief:, "
          "monday_briefing:, temporal:, cache:..., ceo:<job>, ack:<job>:...", S.COUNTERPARTY, R.EPHEMERAL,
          "30 minutes to 7 days", "privacy.ephemeral", (Flow.LLM,)),
    Store("agent_memory", "one narrative and summary per agent run per organisation",
          "table agent_memory_episodes (PostgreSQL) / agent_memory (SQLite), outside the ORM metadata",
          S.COUNTERPARTY, R.OPERATIONAL, "no expiry before this work", "privacy.ephemeral", (Flow.LLM,)),
    Store("agent_checkpoints", "the state of an agent run between steps (what resume reloads): can hold the "
          "statement's rows, figures and narrative of one run",
          "tables checkpoints, checkpoint_blobs, checkpoint_writes (PostgreSQL, created by the langgraph library, "
          "outside the ORM metadata; thread id `<org_id>:<job_id>`)",
          S.COUNTERPARTY, R.OPERATIONAL, "30 days after the run's last step (RETENTION_CHECKPOINT_DAYS)",
          "privacy.ephemeral (inside the erase transaction) and the retention job"),
    Store("llm_provider_side", "prompts and responses as the model provider keeps them", "the provider",
          S.ANYONE, R.OPERATIONAL, "set by the provider, outside our control",
          "cannot be erased by us: lawyer question Q1", (Flow.LLM,)),
    Store("application_logs", "log lines: request paths, error messages that can name a counterparty",
          "container stdout (docker log driver)", S.ANYONE, R.OPERATIONAL,
          "set by the log driver; not defined in this repository", "cannot be erased per organisation"),
    Store("sentry", "error events (keys scrubbed, `send_default_pii=False`)", "Sentry, only when SENTRY_DSN is set",
          S.ANYONE, R.OPERATIONAL, "set by the Sentry project", "cannot be erased by us", (Flow.SENTRY,)),
    Store("backups", "a copy of everything above that is in the database or the volume",
          "the operator's database backups and volume snapshots", S.ANYONE, R.OPERATIONAL,
          "the backup rotation (BACKUP_RETENTION_DAYS of the operator)",
          "NOT purged retroactively: an erased organisation reappears only if a backup is restored; "
          "the restore runbook must re-run the erasure records (see docs/kvkk/yedek-ve-silme.md)"),
)

"""
Email Parser Service — Pasif Intelligence (PLAN.md #2)

Vizyon: Muhasebe yazılımı her ay PDF/Excel rapor emailler.
Kullanıcı bu emaili bizim webhook adresine yönlendiriyor.
Sistem otomatik parse eder → analiz başlatır.

Desteklenen formatlar:
  - multipart/mixed email (RFC 2822)
  - inline attachments (base64 encoded)
  - Paraşüt, Logo Tiger, NetSis email formatları
  - Banka ekstresi emailları (İş Bankası, Garanti, YapıKredi, Akbank)

Pipeline:
  1. POST /email/ingest   → raw email body (MIME)
  2. Extract attachments  → PDF, Excel, CSV
  3. Classify attachment  → financial_statement | bank_statement | invoice
  4. Route to parser      → existing parsers (BankParser, ExcelParser)
  5. Auto-enqueue analysis job
  6. Return job_id

Security:
  - API key authentication for webhook
  - Attachment size limit: 10MB per file
  - Allowed MIME types whitelist
  - Sender domain allowlist (configurable per org)

DDIA: email'i immutable event olarak sakla, parser sonuçlarını ayrı.
"""
from __future__ import annotations

import base64
import email
import email.policy
import hashlib
import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from email.message import Message
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_ATTACHMENTS      = 5

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/plain",
    "application/octet-stream",   # many email clients use this for CSV
}

# Recognise financial attachment by filename patterns
FINANCIAL_PATTERNS = [
    re.compile(r"(hesap|ekstr|banka|odeme|fatura|rapor|gelir|gider|muhasebe)", re.I),
    re.compile(r"(account|statement|invoice|report|balance|transaction)", re.I),
    re.compile(r"\.(pdf|xls|xlsx|csv)$", re.I),
]

BANK_SENDER_PATTERNS = {
    "isbank":    re.compile(r"(isbank|isbankas[ıi])", re.I),
    "garanti":   re.compile(r"garanti", re.I),
    "yapikredi": re.compile(r"(yapikredi|yapi.kredi)", re.I),
    "akbank":    re.compile(r"akbank", re.I),
    "ziraat":    re.compile(r"ziraat", re.I),
    "vakifbank": re.compile(r"vakifbank", re.I),
    "parasut":   re.compile(r"parasut", re.I),
    "logo":      re.compile(r"(logo|tiger)", re.I),
    "netsis":    re.compile(r"netsis", re.I),
    "mikro":     re.compile(r"mikro", re.I),
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ParsedAttachment:
    """Single extracted attachment from an email."""
    filename:    str
    content:     bytes
    mime_type:   str
    size_bytes:  int
    sha256:      str
    source_type: str    # "bank_statement" | "financial_report" | "invoice" | "unknown"
    bank_hint:   str | None = None   # "garanti" | "isbank" | ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename":    self.filename,
            "mime_type":   self.mime_type,
            "size_bytes":  self.size_bytes,
            "sha256":      self.sha256,
            "source_type": self.source_type,
            "bank_hint":   self.bank_hint,
        }


@dataclass
class ParsedEmail:
    """Result of parsing a raw MIME email."""
    message_id:     str
    subject:        str
    sender:         str
    recipient:      str
    date_str:       str
    body_text:      str
    attachments:    list[ParsedAttachment] = field(default_factory=list)
    bank_hint:      str | None = None
    parse_errors:   list[str]  = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id":  self.message_id,
            "subject":     self.subject,
            "sender":      self.sender,
            "recipient":   self.recipient,
            "date_str":    self.date_str,
            "bank_hint":   self.bank_hint,
            "attachments": [a.to_dict() for a in self.attachments],
            "parse_errors": self.parse_errors,
        }


# ── Core parser ───────────────────────────────────────────────────────────────

class EmailParser:
    """
    Parse raw MIME email → extract financial attachments.

    DDIA: pure function, no I/O, no side effects.
    All state lives in the returned ParsedEmail dataclass.
    """

    def parse(self, raw_email: str | bytes) -> ParsedEmail:
        """
        Parse a raw MIME email (RFC 2822 format).

        Accepts:
          - String: UTF-8 encoded email text
          - Bytes: raw MIME bytes
        """
        try:
            if isinstance(raw_email, str):
                raw_email = raw_email.encode("utf-8", errors="replace")

            msg: Message = email.message_from_bytes(
                raw_email,
                policy=email.policy.compat32,
            )
        except Exception as exc:
            logger.error("Email parse failed: %s", exc)
            return ParsedEmail(
                message_id="unknown",
                subject="",
                sender="",
                recipient="",
                date_str="",
                body_text="",
                parse_errors=[f"MIME parse error: {exc}"],
            )

        # ── Extract headers ───────────────────────────────────────────────────
        subject    = self._decode_header(msg.get("Subject", ""))
        sender     = msg.get("From", "")
        recipient  = msg.get("To", "")
        date_str   = msg.get("Date", "")
        message_id = msg.get("Message-ID", str(uuid.uuid4()))

        # ── Detect bank from sender ───────────────────────────────────────────
        bank_hint = self._detect_bank(sender, subject)

        # ── Extract body text ─────────────────────────────────────────────────
        body_text = self._extract_body(msg)

        # If no bank from headers, try body
        if not bank_hint:
            bank_hint = self._detect_bank(body_text, "")

        # ── Extract attachments ───────────────────────────────────────────────
        attachments: list[ParsedAttachment] = []
        parse_errors: list[str] = []

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is None and not part.get_filename():
                continue

            filename  = self._decode_header(part.get_filename() or "")
            mime_type = part.get_content_type() or "application/octet-stream"

            if len(attachments) >= MAX_ATTACHMENTS:
                parse_errors.append(f"Max {MAX_ATTACHMENTS} attachments — skipping '{filename}'")
                break

            # Check MIME type
            if mime_type not in ALLOWED_MIME_TYPES:
                # Also accept if filename has known extension
                if not re.search(r"\.(pdf|xls|xlsx|csv)$", filename, re.I):
                    logger.debug("Skipping attachment: mime=%s filename=%s", mime_type, filename)
                    continue

            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                if len(payload) > MAX_ATTACHMENT_BYTES:
                    parse_errors.append(
                        f"Attachment '{filename}' too large: {len(payload) // 1024}KB (max 10MB)"
                    )
                    continue

                sha256 = hashlib.sha256(payload).hexdigest()
                source_type = self._classify_attachment(filename, mime_type, bank_hint)

                attachments.append(ParsedAttachment(
                    filename    = filename or f"attachment_{len(attachments)+1}",
                    content     = payload,
                    mime_type   = mime_type,
                    size_bytes  = len(payload),
                    sha256      = sha256,
                    source_type = source_type,
                    bank_hint   = bank_hint,
                ))

            except Exception as exc:
                parse_errors.append(f"Failed to decode '{filename}': {exc}")

        return ParsedEmail(
            message_id  = message_id,
            subject     = subject,
            sender      = sender,
            recipient   = recipient,
            date_str    = date_str,
            body_text   = body_text[:2000],   # cap body size
            attachments = attachments,
            bank_hint   = bank_hint,
            parse_errors= parse_errors,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _decode_header(value: str | None) -> str:
        """Decode RFC 2047 encoded header (=?UTF-8?...?=)."""
        if not value:
            return ""
        try:
            parts = email.header.decode_header(value)
            decoded = []
            for part, charset in parts:
                if isinstance(part, bytes):
                    decoded.append(part.decode(charset or "utf-8", errors="replace"))
                else:
                    decoded.append(part)
            return " ".join(decoded)
        except Exception:
            return str(value)

    @staticmethod
    def _extract_body(msg: Message) -> str:
        """Extract plain-text body from MIME message."""
        body_parts = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
        return "\n".join(body_parts)

    @staticmethod
    def _detect_bank(text: str, subject: str) -> str | None:
        """Detect bank/software from email text and subject."""
        combined = f"{text} {subject}".lower()
        for bank_name, pattern in BANK_SENDER_PATTERNS.items():
            if pattern.search(combined):
                return bank_name
        return None

    @staticmethod
    def _classify_attachment(filename: str, mime_type: str, bank_hint: str | None) -> str:
        """Classify attachment type based on filename + context."""
        fn = filename.lower()

        if bank_hint:
            return "bank_statement"

        if re.search(r"(fatura|invoice|bill)", fn, re.I):
            return "invoice"

        if re.search(r"(ekstr|statement|hesap)", fn, re.I):
            return "bank_statement"

        if re.search(r"(rapor|report|gelir|gider|pnl|bilanço|balance)", fn, re.I):
            return "financial_report"

        if mime_type in ("text/csv", "text/plain") or fn.endswith(".csv"):
            return "financial_report"

        if any(p.search(fn) for p in FINANCIAL_PATTERNS):
            return "financial_report"

        return "unknown"


# ── Global singleton ──────────────────────────────────────────────────────────

_parser: EmailParser | None = None


def get_email_parser() -> EmailParser:
    """Global singleton email parser."""
    global _parser
    if _parser is None:
        _parser = EmailParser()
    return _parser


# ── Org allowlist helper ──────────────────────────────────────────────────────

def extract_sender_domain(sender: str) -> str | None:
    """Extract domain from email address."""
    match = re.search(r"@([\w.-]+)", sender)
    return match.group(1).lower() if match else None


def generate_ingest_address(org_id: str) -> str:
    """
    Generate a unique email ingest address for an org.

    Format: ingest+{hash}@{domain}
    Users configure their accounting software to CC this address.
    """
    from app.config import get_settings
    settings = get_settings()
    domain = getattr(settings, "email_ingest_domain", "ingest.agentic-cfo.io")
    # Short deterministic hash of org_id
    org_hash = hashlib.sha256(org_id.encode()).hexdigest()[:12]
    return f"ingest+{org_hash}@{domain}"

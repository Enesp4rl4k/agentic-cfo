"""
Data Ingestion Agent — Skill 1 of 5.

Responsibility: Read the uploaded file (PDF/Excel/CSV), extract raw text
and structured transactions, persist them to the DB.

Confidence signals:
- 1.0  → all transactions parsed with vendor + amount + date
- 0.85 → some fields missing but majority parseable
- 0.60 → low-quality OCR or too many unparseable rows → triggers review gate
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "revenue":        ["sales", "income", "revenue", "payment received", "invoice issued"],
    "cogs":           ["raw material", "goods", "product cost", "manufacturing", "inventory"],
    "salary":         ["salary", "payroll", "wages", "employee", "social security", "staff"],
    "rent":           ["rent", "lease", "office rent"],
    "utilities":      ["electricity", "water", "gas", "internet", "phone", "telecom"],
    "marketing":      ["advertising", "marketing", "google ads", "meta ads", "social media", "campaign"],
    "technology":     ["software", "server", "cloud", "aws", "azure", "saas", "subscription", "license"],
    "tax":            ["tax", "vat", "withholding", "corporate tax", "income tax"],
    "loan":           ["loan", "debt", "interest", "installment", "bank payment", "credit"],
    "other_expense":  [],
    "other_income":   [],
}


def _guess_category(description: str) -> str:
    desc_lower = description.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in desc_lower for kw in keywords):
            return category
    return "other_expense"


def _parse_amount(raw: str) -> int | None:
    """Parse an amount string into the smallest currency unit (cents/kurus)."""
    cleaned = re.sub(r"[^\d,.]", "", raw.replace(",", "."))
    try:
        return int(float(cleaned) * 100)
    except (ValueError, TypeError):
        return None


def _parse_date(raw: str) -> datetime | None:
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def _extract_transactions_with_llm(
    raw_text: str, settings
) -> list[dict[str, Any]]:
    """
    Use GPT-4o to extract structured transactions from raw document text.
    Returns list of dicts: date, amount, type, description, vendor, confidence.
    """
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.0,
        max_tokens=4096,
        api_key=settings.openai_api_key,
    )
    system = (
        "You are a financial data extraction specialist. "
        "Extract all financial transactions from the provided document text as a JSON array.\n"
        "For each transaction include:\n"
        "- date: transaction date (DD.MM.YYYY or YYYY-MM-DD)\n"
        "- amount: numeric amount (no currency symbol)\n"
        "- type: 'income' or 'expense'\n"
        "- description: transaction description\n"
        "- vendor: supplier or customer name (null if unknown)\n"
        "- confidence: confidence score 0-1 for this extraction\n\n"
        "Respond with ONLY a valid JSON array. No explanation, no markdown.\n"
        'Example: [{"date": "15.03.2024", "amount": 1500.00, "type": "expense", '
        '"description": "Electricity bill", "vendor": "City Power Co.", "confidence": 0.95}]'
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"Document text:\n\n{raw_text[:8000]}"),
    ]
    import json
    response = await llm.ainvoke(messages)
    content = response.content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return json.loads(content)


def _read_pdf(file_path: str) -> str:
    import fitz  # PyMuPDF
    text_parts: list[str] = []
    with fitz.open(file_path) as doc:
        for page in doc:
            text_parts.append(page.get_text())
    return "\n".join(text_parts)


def _read_excel(file_path: str) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(file_path, read_only=True, data_only=True)
    rows: list[str] = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                rows.append("\t".join(cells))
    return "\n".join(rows)


def _read_csv(file_path: str) -> str:
    with open(file_path, encoding="utf-8-sig", newline="") as f:
        return f.read()


async def run_data_ingestion(
    state: CFOState, config: AgentRunConfig
) -> SkillResult:
    """
    Data Ingestion Skill.
    done_when: state['transactions'] is a non-empty list.
    """
    settings = get_settings()
    file_path = state.get("file_path", "")
    file_type = state.get("file_type", "")

    if not os.path.exists(file_path):
        return SkillResult(ok=False, detail=f"File not found: {file_path}", halt=True)

    try:
        if file_type == "pdf":
            raw_text = _read_pdf(file_path)
        elif file_type in ("xlsx", "xls"):
            raw_text = _read_excel(file_path)
        elif file_type == "csv":
            raw_text = _read_csv(file_path)
        else:
            return SkillResult(ok=False, detail=f"Unsupported file type: {file_type}", halt=True)

        if not raw_text.strip():
            return SkillResult(
                ok=False,
                detail="Could not extract any text from the file.",
                needs_review=True,
                confidence=0.0,
            )

        raw_transactions = await _extract_transactions_with_llm(raw_text, settings)

        if not raw_transactions:
            return SkillResult(
                ok=False,
                detail="LLM returned no transactions from the document.",
                needs_review=True,
                confidence=0.4,
            )

        transactions: list[dict[str, Any]] = []
        confidences: list[float] = []

        for t in raw_transactions:
            amount_cents = _parse_amount(str(t.get("amount", "")))
            parsed_date = _parse_date(str(t.get("date", "")))
            conf = float(t.get("confidence", 0.8))
            confidences.append(conf)

            transactions.append({
                "amount_cents": amount_cents or 0,
                "currency": "USD",
                "type": t.get("type", "expense"),
                "category": _guess_category(t.get("description", "")),
                "description": t.get("description", ""),
                "vendor": t.get("vendor"),
                "transaction_date": parsed_date.isoformat() if parsed_date else None,
                "raw_text": str(t),
                "confidence": conf,
            })

        overall_confidence = min(confidences) if confidences else 0.5
        parseable = sum(
            1 for tx in transactions
            if tx["amount_cents"] > 0 and tx["transaction_date"]
        )
        parse_ratio = parseable / len(transactions) if transactions else 0

        if parse_ratio < 0.5:
            overall_confidence = min(overall_confidence, 0.55)
        elif parse_ratio < 0.8:
            overall_confidence = min(overall_confidence, 0.75)

        return SkillResult(
            ok=True,
            patch={"raw_text": raw_text, "transactions": transactions},
            confidence=overall_confidence,
            needs_review=overall_confidence < 0.80,
            detail=(
                f"Extracted {len(transactions)} transactions "
                f"({parseable} fully parsed, confidence={overall_confidence:.2f})"
            ),
        )

    except Exception as exc:
        logger.exception("Data ingestion failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Ingestion error: {exc}", halt=True)

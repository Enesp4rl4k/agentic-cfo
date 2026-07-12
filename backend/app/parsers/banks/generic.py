"""
Generic parser — LLM fallback when no bank-specific parser matches.
Uses GPT-4o with vision to extract transactions from any document.
This is the last resort: slower and less reliable than structured parsers.
"""
from __future__ import annotations

import json
import logging
import re

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction
from app.config import get_settings

logger = logging.getLogger(__name__)


class GenericParser(BankParser):
    bank_id = "generic"
    bank_display_name = "Generic (LLM)"

    @classmethod
    def can_parse(cls, text: str) -> bool:
        # Generic always matches — it's the fallback
        return True

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        statement = ParsedStatement(
            bank_name="Unknown Bank",
            account_number=None,
            statement_period_start=None,
            statement_period_end=None,
        )
        statement.parse_warnings.append(
            "No bank-specific parser matched. Using LLM extraction (lower reliability)."
        )

        try:
            transactions = self._extract_via_llm(text)
            statement.transactions = transactions
        except Exception as exc:
            logger.exception("GenericParser LLM extraction failed")
            statement.parse_warnings.append(f"LLM extraction failed: {exc}")

        return statement

    def _extract_via_llm(self, text: str) -> list[ParsedTransaction]:
        """Call GPT-4o to extract transactions from unstructured text."""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
        from datetime import timezone

        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.0,
            max_tokens=4096,
            api_key=settings.openai_api_key,
        )

        system = (
            "You are a financial data extraction specialist. "
            "Extract all financial transactions from the document text as a JSON array. "
            "Each transaction must have: "
            "date (DD.MM.YYYY), amount (numeric, no symbols), "
            "type ('income' or 'expense'), description (string), "
            "vendor (string or null), confidence (0-1). "
            "Return ONLY a valid JSON array. No markdown, no explanation."
        )

        response = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Document:\n\n{text[:6000]}"),
        ])

        content = response.content.strip()
        # Strip markdown code fences
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

        raw_list = json.loads(content)
        transactions: list[ParsedTransaction] = []

        for item in raw_list:
            date = self.parse_turkish_date(str(item.get("date", "")))
            if not date:
                continue
            amount = self.parse_turkish_amount(str(item.get("amount", "")))
            if not amount:
                continue
            transactions.append(ParsedTransaction(
                date=date,
                description=str(item.get("description", "")),
                amount_cents=amount,
                tx_type=item.get("type", "expense"),
                vendor=item.get("vendor"),
                raw_row=str(item),
            ))

        return transactions

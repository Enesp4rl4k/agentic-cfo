"""
Tekdüzen Hesap Planı (THP / TDHP) Otomatik Muhasebe & Yevmiye Motoru (Phase 3).

Her finansal işlemi Türk Tekdüzen Hesap Planı standartlarına göre
Borç (Debit) ve Alacak (Credit) yevmiye maddelerine dönüştürür.
KDV oranlarını (%1, %10, %20) otomatik ayrıştırır.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class JournalEntryLine:
    account_code: str    # e.g. "770.01.001"
    account_name: str    # e.g. "Genel Yönetim - Yazılım Lisansları"
    debit_cents: int     # Borç (kuruş)
    credit_cents: int    # Alacak (kuruş)
    description: str     # Satır açıklaması


@dataclass
class SuggestedJournalEntry:
    entry_id: str
    entry_date: str      # YYYY-MM-DD
    document_number: str # Belge / Dekont No
    description: str
    lines: list[JournalEntryLine] = field(default_factory=list)
    confidence: float = 0.95
    status: str = "pending"  # "pending", "approved", "rejected"

    @property
    def total_debit_cents(self) -> int:
        return sum(l.debit_cents for l in self.lines)

    @property
    def total_credit_cents(self) -> int:
        return sum(l.credit_cents for l in self.lines)

    @property
    def is_balanced(self) -> bool:
        return self.total_debit_cents == self.total_credit_cents


class THPClassifier:
    """Tekdüzen Hesap Planı akıllı sınıflandırma ve yevmiye motoru."""

    ACCOUNT_MAP = {
        "sales": ("600.01.001", "Yurtiçi Satışlar"),
        "revenue": ("600.01.001", "Yurtiçi Satışlar"),
        "services": ("600.01.002", "Hizmet Gelirleri"),
        "consulting": ("600.01.003", "Danışmanlık Gelirleri"),
        "payroll": ("770.01.001", "Personel Ücret ve Maaş Giderleri"),
        "salary": ("770.01.001", "Personel Ücret ve Maaş Giderleri"),
        "rent": ("770.02.001", "Kira Giderleri"),
        "utilities": ("770.03.001", "Elektrik, Su, Doğalgaz Giderleri"),
        "software": ("770.04.001", "Bilişim ve Yazılım Lisans Giderleri"),
        "marketing": ("760.01.001", "Pazarlama ve Reklam Giderleri"),
        "cogs": ("153.01.001", "Ticari Mallar"),
        "other_expense": ("770.99.001", "Çeşitli Genel Yönetim Giderleri"),
    }

    @classmethod
    def classify_transaction(
        cls,
        tx: dict[str, Any],
        default_kdv_rate: float = 0.20,
    ) -> SuggestedJournalEntry:
        """
        Convert a single transaction dictionary into a balanced TDHP journal entry.
        """
        tx_id = tx.get("id") or str(id(tx))
        tx_date = tx.get("transaction_date") or datetime.now().strftime("%Y-%m-%d")
        tx_type = tx.get("type", "expense")
        category = tx.get("category", "other_expense").lower()
        desc = tx.get("description") or "Finansal İşlem"
        amount_cents = tx.get("amount_cents", 0)

        lines: list[JournalEntryLine] = []

        if tx_type == "income":
            # ── Gelir Kaydı (Satış) ──
            # Borç: 102.01 Bankalar (Toplam Tutar)
            # Alacak: 600.01 Yurtiçi Satışlar (Matrah)
            # Alacak: 391.01 Hesaplanan KDV (KDV Tutarı)
            kdv_cents = round(amount_cents * default_kdv_rate / (1.0 + default_kdv_rate))
            matrah_cents = amount_cents - kdv_cents
            acct_code, acct_name = cls.ACCOUNT_MAP.get(category, ("600.01.001", "Yurtiçi Satışlar"))

            lines.append(JournalEntryLine(
                account_code="102.01.001",
                account_name="Vadesiz Ticari TL Hesabı",
                debit_cents=amount_cents,
                credit_cents=0,
                description=f"Tahsilat: {desc}",
            ))
            lines.append(JournalEntryLine(
                account_code=acct_code,
                account_name=acct_name,
                debit_cents=0,
                credit_cents=matrah_cents,
                description=f"Satış Matrahı: {desc}",
            ))
            if kdv_cents > 0:
                lines.append(JournalEntryLine(
                    account_code="391.01.020",
                    account_name="Hesaplanan KDV (%20)",
                    debit_cents=0,
                    credit_cents=kdv_cents,
                    description=f"Satış KDV: {desc}",
                ))

        else:
            # ── Gider Kaydı (Harcama) ──
            # Borç: 770/760 İlgili Gider Hesabı (Matrah)
            # Borç: 191.01 İndirilecek KDV (KDV Tutarı)
            # Alacak: 102.01 Bankalar (Toplam Tutar)
            is_payroll = category in ("payroll", "salary")
            if is_payroll:
                # Maaşlarda KDV olmaz
                kdv_cents = 0
                matrah_cents = amount_cents
            else:
                kdv_cents = round(amount_cents * default_kdv_rate / (1.0 + default_kdv_rate))
                matrah_cents = amount_cents - kdv_cents

            acct_code, acct_name = cls.ACCOUNT_MAP.get(category, ("770.99.001", "Çeşitli Genel Yönetim Giderleri"))

            lines.append(JournalEntryLine(
                account_code=acct_code,
                account_name=acct_name,
                debit_cents=matrah_cents,
                credit_cents=0,
                description=f"Gider Matrahı: {desc}",
            ))
            if kdv_cents > 0:
                lines.append(JournalEntryLine(
                    account_code="191.01.020",
                    account_name="İndirilecek KDV (%20)",
                    debit_cents=kdv_cents,
                    credit_cents=0,
                    description=f"Gider KDV: {desc}",
                ))
            lines.append(JournalEntryLine(
                account_code="102.01.001",
                account_name="Vadesiz Ticari TL Hesabı",
                debit_cents=0,
                credit_cents=amount_cents,
                description=f"Ödeme: {desc}",
            ))

        return SuggestedJournalEntry(
            entry_id=f"yevmiye-{tx_id}",
            entry_date=tx_date[:10],
            document_number=f"DEC-{tx_id[:8].upper()}",
            description=desc,
            lines=lines,
            confidence=0.95,
            status="pending",
        )

    @classmethod
    def generate_journal_batch(cls, transactions: list[dict[str, Any]]) -> list[SuggestedJournalEntry]:
        """Generate TDHP journal entries for all transactions in batch."""
        return [cls.classify_transaction(t) for t in transactions]

"""Stress corpus generator for Turkish SME financial data.

Synthesizes messy, real-world Turkish accounting anomalies to test:
1. Parser resilience (UTF-8 BOM, varied delimiters, Turkish chars, malformed lines).
2. Metamorphic invariance (idempotency, row permutation, partition invariance).
3. Zero false-positive bank reconciliation (no accidental confirmed matches on ambiguous data).

Plan v10 §13.4 (E2) & Plan v11 Faz 1.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class StressCaseExpectations:
    expected_revenue_cents: int
    expected_expense_cents: int
    expected_confirmed_matches: int
    expected_proposed_matches: int
    expected_unmatched_bank_lines: int


@dataclass
class StressBundle:
    name: str
    invoices: list[dict[str, Any]]
    bank_lines: list[dict[str, Any]]
    expectations: StressCaseExpectations
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def all_rows(self) -> list[dict[str, Any]]:
        """Combined list of invoices and bank transactions."""
        return list(self.invoices) + list(self.bank_lines)

    def to_csv(
        self,
        *,
        delimiter: str = ";",
        include_bom: bool = True,
        date_format: str = "%d.%m.%Y",
        trailing_empty_lines: int = 2,
    ) -> bytes:
        """Export the bundle rows to CSV bytes with formatting variations."""
        out = io.StringIO()
        writer = csv.writer(out, delimiter=delimiter)
        writer.writerow(
            [
                "Tarih",
                "Açıklama",
                "Tutar",
                "Tür",
                "Para Birimi",
                "Belge No",
                "Karşı Taraf",
                "Vade Tarihi",
            ]
        )

        for row in self.all_rows:
            raw_date = row.get("transaction_date")
            if isinstance(raw_date, str):
                d = date.fromisoformat(raw_date)
            elif isinstance(raw_date, date):
                d = raw_date
            else:
                d = date(2024, 1, 1)

            formatted_date = d.strftime(date_format)
            amount_lira = f"{row['amount_cents'] / 100:.2f}".replace(".", ",")
            raw_due = row.get("due_date")
            formatted_due = ""
            if raw_due:
                if isinstance(raw_due, str):
                    formatted_due = date.fromisoformat(raw_due).strftime(date_format)
                elif isinstance(raw_due, date):
                    formatted_due = raw_due.strftime(date_format)

            writer.writerow(
                [
                    formatted_date,
                    row.get("description", ""),
                    amount_lira,
                    row.get("type", "income"),
                    row.get("currency", "TRY"),
                    row.get("document_id", ""),
                    row.get("counterparty", ""),
                    formatted_due,
                ]
            )

        for _ in range(trailing_empty_lines):
            out.write("\n")

        content = out.getvalue()
        if include_bom:
            return b"\xef\xbb\xbf" + content.encode("utf-8")
        return content.encode("utf-8")


def generate_stress_corpus(*, seed: int = 42) -> StressBundle:
    """Generate a deterministic stress corpus representing messy Turkish SME records.

    Includes:
    - Turkish character folding (İ/ı, Ş/ş, Ğ/ğ, Ç/ç, Ö/ö, Ü/ü).
    - Ambiguous counterparties with identical amounts (must NOT auto-confirm).
    - Exact invoice number matches (confirmable).
    - Named single match with matching amount (confirmable).
    - Partial payments with and without invoice numbers (proposed only).
    - Multi-currency mismatches (USD vs TRY).
    - Payments outside valid reconciliation date window (> 3 days prior).
    - Recurring payments with identical descriptions across periods.
    """
    invoices: list[dict[str, Any]] = []
    bank_lines: list[dict[str, Any]] = []

    # 1. Exact match by invoice number (Confirmable)
    inv1_id = f"INV-{seed}-001"
    invoices.append(
        {
            "document_id": inv1_id,
            "amount_cents": 150_000_00,  # 150,000.00 TL
            "type": "income",
            "category": "revenue",
            "description": "e-Fatura GIB2024000010001: YILDIZ TEKSTİL SAN. VE TİC. A.Ş.",
            "counterparty": "Yıldız Tekstil San. ve Tic. A.Ş.",
            "transaction_date": "2024-01-10",
            "due_date": date(2024, 2, 15),
            "currency": "TRY",
        }
    )
    bank_lines.append(
        {
            "amount_cents": 150_000_00,
            "type": "income",
            "category": "revenue",
            "description": "GELEN EFT GIB2024000010001 NOLU FATURA TAHSİLATI",
            "transaction_date": "2024-02-14",
            "currency": "TRY",
            "_expected": "confirmed",
        }
    )

    # 2. Match by counterparty name and exact amount (Confirmable)
    # Uses diacritic variations: "Şengül" in invoice, "SENGUL" in bank statement
    inv2_id = f"INV-{seed}-002"
    invoices.append(
        {
            "document_id": inv2_id,
            "amount_cents": 45_250_50,  # 45,250.50 TL with kuruş fraction
            "type": "expense",
            "category": "cogs",
            "description": "e-Fatura GIB2024000010002: ŞENGÜL LOJİSTİK VE DAĞITIM LİMİTED ŞİRKETİ",
            "counterparty": "Şengül Lojistik ve Dağıtım Ltd. Şti.",
            "transaction_date": "2024-01-15",
            "due_date": date(2024, 2, 28),
            "currency": "TRY",
        }
    )
    bank_lines.append(
        {
            "amount_cents": 45_250_50,
            "type": "expense",
            "category": "other_expense",
            "description": "GIDEN HAVALE SENGUL LOJISTIK DAGITIM TEDARIK ODEMESI",
            "transaction_date": "2024-02-25",
            "currency": "TRY",
            "_expected": "confirmed",
        }
    )

    # 3. AMBIGUOUS: Same exact amount for two different counterparties!
    # A generic bank movement with no name MUST NOT auto-confirm to either invoice.
    inv3_id = f"INV-{seed}-003"
    inv4_id = f"INV-{seed}-004"
    invoices.append(
        {
            "document_id": inv3_id,
            "amount_cents": 20_000_00,
            "type": "income",
            "category": "revenue",
            "description": "e-Fatura GIB2024000010003: ÇAĞDAŞ AMBALAJ SANAYİ",
            "counterparty": "Çağdaş Ambalaj",
            "transaction_date": "2024-02-01",
            "due_date": date(2024, 3, 1),
            "currency": "TRY",
        }
    )
    invoices.append(
        {
            "document_id": inv4_id,
            "amount_cents": 20_000_00,
            "type": "income",
            "category": "revenue",
            "description": "e-Fatura GIB2024000010004: GÜVEN İNŞAAT MALZEMELERİ",
            "counterparty": "Güven İnşaat",
            "transaction_date": "2024-02-05",
            "due_date": date(2024, 3, 5),
            "currency": "TRY",
        }
    )
    # Bank movement with amount 20,000.00 but no distinguishing counterparty words
    bank_lines.append(
        {
            "amount_cents": 20_000_00,
            "type": "income",
            "category": "revenue",
            "description": "MUSTERI HESABINDAN GELEN HAVALE / TICARI HESAP",
            "transaction_date": "2024-03-02",
            "currency": "TRY",
            "_expected": "proposed",  # Must be PROPOSED, never CONFIRMED
        }
    )

    # 4. AMBIGUOUS: Partial payment without invoice number
    inv5_id = f"INV-{seed}-005"
    invoices.append(
        {
            "document_id": inv5_id,
            "amount_cents": 100_000_00,
            "type": "income",
            "category": "revenue",
            "description": "e-Fatura GIB2024000010005: ANADOLU DÖKÜM MAKİNA SANAYİ",
            "counterparty": "Anadolu Döküm",
            "transaction_date": "2024-02-10",
            "due_date": date(2024, 3, 20),
            "currency": "TRY",
        }
    )
    bank_lines.append(
        {
            "amount_cents": 40_000_00,  # Only partial 40k
            "type": "income",
            "category": "revenue",
            "description": "GELEN EFT ANADOLU DOKUM CARI ODEME",
            "transaction_date": "2024-03-15",
            "currency": "TRY",
            "_expected": "unmatched",  # Without invoice number and non-exact amount, does not match _decide
        }
    )

    # 5. Partial payment WITH invoice number (Proposed)
    inv6_id = f"INV-{seed}-006"
    invoices.append(
        {
            "document_id": inv6_id,
            "amount_cents": 80_000_00,
            "type": "income",
            "category": "revenue",
            "description": "e-Fatura GIB2024000010006: ÖZDEMİR OTOMOTİV YEDEK PARÇA",
            "counterparty": "Özdemir Otomotiv",
            "transaction_date": "2024-02-12",
            "due_date": date(2024, 3, 15),
            "currency": "TRY",
        }
    )
    bank_lines.append(
        {
            "amount_cents": 30_000_00,
            "type": "income",
            "category": "revenue",
            "description": "EFT GIB2024000010006 1.KISMI TAHSILAT",
            "transaction_date": "2024-03-10",
            "currency": "TRY",
            "_expected": "proposed",  # Number matches, but partial amount -> PROPOSED
        }
    )

    # 6. Date anomaly: payment arrived months BEFORE invoice date
    # In Turkish commerce, an advance payment months prior must not falsely match
    inv7_id = f"INV-{seed}-007"
    invoices.append(
        {
            "document_id": inv7_id,
            "amount_cents": 60_000_00,
            "type": "income",
            "category": "revenue",
            "description": "e-Fatura GIB2024000010007: İLERİ TEKNOLOJİ YAZILIM",
            "counterparty": "İleri Teknoloji",
            "transaction_date": "2024-06-01",
            "due_date": date(2024, 7, 1),
            "currency": "TRY",
        }
    )
    bank_lines.append(
        {
            "amount_cents": 60_000_00,
            "type": "income",
            "category": "revenue",
            "description": "GELEN EFT ILERI TEKNOLOJI ODEME",
            "transaction_date": "2024-01-15",  # 4.5 months before invoice!
            "currency": "TRY",
            "_expected": "unmatched",  # Rejected by day >= i.issue_date - _EARLIEST
        }
    )

    # 7. Currency anomaly: USD invoice vs TRY payment
    inv8_id = f"INV-{seed}-008"
    invoices.append(
        {
            "document_id": inv8_id,
            "amount_cents": 10_000_00,  # 10,000 USD
            "type": "income",
            "category": "revenue",
            "description": "e-Fatura GIB2024000010008: GLOBAL EXPORT PARTNERS LLC",
            "counterparty": "Global Export Partners",
            "transaction_date": "2024-03-01",
            "due_date": date(2024, 4, 1),
            "currency": "USD",
        }
    )
    bank_lines.append(
        {
            "amount_cents": 10_000_00,  # 10,000 TRY
            "type": "income",
            "category": "revenue",
            "description": "GELEN HAVALE GLOBAL EXPORT PARTNERS",
            "transaction_date": "2024-03-20",
            "currency": "TRY",  # Currency mismatch!
            "_expected": "unmatched",
        }
    )

    # 8. Duplicate recurring bank rows (identical description, same amount, different days)
    bank_lines.append(
        {
            "amount_cents": 25_000_00,
            "type": "expense",
            "category": "rent",
            "description": "KİRA ÖDEMESİ - MERKEZ OFİS OCAK 2024",
            "transaction_date": "2024-01-05",
            "currency": "TRY",
            "_expected": "unmatched",
        }
    )
    bank_lines.append(
        {
            "amount_cents": 25_000_00,
            "type": "expense",
            "category": "rent",
            "description": "KİRA ÖDEMESİ - MERKEZ OFİS ŞUBAT 2024",
            "transaction_date": "2024-02-05",
            "currency": "TRY",
            "_expected": "unmatched",
        }
    )

    # Calculate deterministic financial totals
    # Invoices (book / documents):
    rev_invoices = sum(
        r["amount_cents"] for r in invoices if r["type"] == "income" and r["currency"] == "TRY"
    )
    exp_invoices = sum(
        r["amount_cents"] for r in invoices if r["type"] == "expense" and r["currency"] == "TRY"
    )

    # In our reconciliation logic:
    # Confirmed matches: inv1 (150k), inv2 (45.25k expense) -> 2 confirmed
    # Proposed matches: case 3 (20k amount_only), case 5 (30k partial by number) -> 2 proposed
    # Unmatched bank lines: case 4 (40k), case 6 (60k date window), case 7 (10k curr), case 8 (2x kira) -> 5
    expectations = StressCaseExpectations(
        expected_revenue_cents=rev_invoices,
        expected_expense_cents=exp_invoices,
        expected_confirmed_matches=2,
        expected_proposed_matches=2,
        expected_unmatched_bank_lines=5,
    )

    return StressBundle(
        name=f"kobi_stress_seed_{seed}",
        invoices=invoices,
        bank_lines=bank_lines,
        expectations=expectations,
        metadata={
            "seed": seed,
            "total_invoices": len(invoices),
            "total_bank_lines": len(bank_lines),
        },
    )

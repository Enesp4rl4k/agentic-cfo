"""A realistic two-page Garanti text statement as the #124 review wrote it: invoice-number wrapped lines
(`FTR 2025000123 nolu fatura tahsilati`), a `Ref:` merged into an FTR line, and page footers carrying a year, a
copyright line and an issue date WITH a time. Committed as a fixture: the noise test counts held non-transaction lines."""


def _tr(n: float) -> str:
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def two_page_with_invoices(rows: int = 20) -> tuple[str, int]:
    """(text, number of real transaction rows)."""
    lines, balance, invoice = [], 100000.0, 2025000123
    for i in range(1, rows + 1):
        amount = (-1) ** i * i * 150.0
        balance += amount
        lines.append(f"{i:02d}.01.2026 {i:02d}.01.2026 Hareket {i} {'+' if amount > 0 else '-'}{_tr(abs(amount))} {_tr(balance)}")
        if i % 4 == 0:                                   # a wrapped description naming the invoice it settles
            lines.append(f"FTR {invoice} nolu fatura tahsilati")
            invoice += 1
        if i == 7:
            lines.append(f"FTR {invoice} Ref: 98765432 nolu fatura")      # a Ref: merged into an FTR line
            invoice += 1
    head = [
        "GARANTİ BBVA Hesap Ekstresi",
        "T. Garanti Bankası A.Ş. Nispetiye Mah. Aytar Cad. No: 2 Beşiktaş 34340 İstanbul",
        "Müşteri Hizmetleri: 0 850 222 0 333  Faks: 0 212 318 18 18",
        "Hesap No: 9876-5432   IBAN TR33 0006 1005 1978 6457 8413 26",
        "Dönem: 01.01.2026 - 31.01.2026",
        "Tarih Valör Açıklama Tutar Bakiye",
    ]
    foot = ["www.garantibbva.com.tr  444 0 333", "© 2026 Garanti BBVA", "2026", "Düzenleme tarihi: 01.02.2026 14:32"]
    half = len(lines) // 2
    return "\n".join([*head, *lines[:half], "Sayfa 1 / 2", *foot, "GARANTİ BBVA Hesap Ekstresi",
                      "Tarih Valör Açıklama Tutar Bakiye", *lines[half:], "Sayfa 2 / 2", *foot]) + "\n", rows

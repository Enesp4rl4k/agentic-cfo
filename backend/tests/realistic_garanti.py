"""A realistic two-page Garanti text statement (address, spaced phone/fax numbers, postcode, years, footers)."""


def _tr(n: float) -> str:
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def two_page_statement(rows: int = 20) -> str:
    lines, balance = [], 100000.0
    for i in range(1, rows + 1):
        amount = (-1) ** i * i * 150.0
        balance += amount
        lines.append(f"{i:02d}.01.2026 {i:02d}.01.2026 Hareket {i} {'+' if amount > 0 else '-'}{_tr(abs(amount))} {_tr(balance)}")
    head = [
        "GARANTİ BBVA Hesap Ekstresi",
        "T. Garanti Bankası A.Ş. Nispetiye Mah. Aytar Cad. No: 2 Beşiktaş 34340 İstanbul",
        "Müşteri Hizmetleri: 0 850 222 0 333  Faks: 0 212 318 18 18",
        "Hesap No: 9876-5432   IBAN TR33 0006 1005 1978 6457 8413 26",
        "Dönem: 01.01.2026 - 31.01.2026",
        "Tarih Valör Açıklama Tutar Bakiye",
    ]
    foot = ["www.garantibbva.com.tr  444 0 333", "Bu belge 2026 yılı içindir.", "© 2026 Garanti BBVA"]
    half = rows // 2
    return "\n".join([*head, *lines[:half], "Sayfa 1 / 2", *foot, "GARANTİ BBVA Hesap Ekstresi",
                      "Tarih Valör Açıklama Tutar Bakiye", *lines[half:], "Sayfa 2 / 2", *foot,
                      "Düzenleme tarihi 01.02.2026"]) + "\n"

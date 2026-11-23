"""ISO-4217 codes in current use: what a person may correct a row's currency to."""
from __future__ import annotations

ISO_4217: frozenset[str] = frozenset(
    ["AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN", "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY", "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR", "ILS", "INR", "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX", "USD", "UYU", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF", "XPF", "YER", "ZAR", "ZMW", "ZWL"]
)


def is_currency_code(code: str | None) -> bool:
    return (code or "").strip().upper() in ISO_4217


# ISO 4217 minor units (the exponent) where it is not 2. The ONE table: a provider that states amounts in the
# currency's smallest unit (Stripe) is converted through it, never by a flat "/ 100".
MINOR_UNIT_EXPONENT: dict[str, int] = {
    **dict.fromkeys(("BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"), 0),
    **dict.fromkeys(("BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"), 3),
}
STORED_EXPONENT = 2   # every amount in the books is an integer of 1/100 of the currency unit ("kuruş")


def minor_exponent(code: str | None, overrides: dict[str, int] | None = None) -> int | None:
    """The currency's minor-unit exponent (2 unless the table says otherwise); None for a code that is not a currency."""
    text = (code or "").strip().upper()
    if not is_currency_code(text):
        return None
    return (overrides or {}).get(text, MINOR_UNIT_EXPONENT.get(text, 2))


def minor_to_cents(minor: int, code: str | None, overrides: dict[str, int] | None = None) -> int | None:
    """An amount in a currency's smallest unit as the books' integer 1/100s, or None when that cannot be exact.

    Never rounded: a three-decimal amount that is not a whole number of 1/100s (KWD 1,234) has no exact figure in
    the books, and an unknown currency has no exponent; both return None so the row is held, not guessed."""
    exponent = minor_exponent(code, overrides)
    if exponent is None or isinstance(minor, bool) or not isinstance(minor, int):
        return None
    if exponent <= STORED_EXPONENT:
        return minor * 10 ** (STORED_EXPONENT - exponent)
    step = 10 ** (exponent - STORED_EXPONENT)
    return minor // step if minor % step == 0 else None


def cents_text(cents: int) -> str:
    """Integer 1/100s as exact decimal text ("1234.56"): what the amount parser reads without ambiguity."""
    sign, whole, frac = ("-" if cents < 0 else ""), abs(cents) // 100, abs(cents) % 100
    return f"{sign}{whole}.{frac:02d}"

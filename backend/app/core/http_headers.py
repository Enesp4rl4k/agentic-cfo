"""HTTP başlıkları latin-1'dir. Türkçe değildir.

An HTTP header value is encoded as latin-1 (RFC 7230 / WSGI), and latin-1 does
not contain ı, ğ, ş or İ. It *does* contain ö, ü and ç, which is what makes this
so easy to miss: "Öztürk Holding" downloads fine and "Yıldız Tekstil" returns a
500, from the same line of code.

Three report endpoints built their download filename straight from the company
name. On a product for Turkish family businesses, that is a crash on the
majority of them.

The fix is RFC 6266: send an ASCII `filename` that any client can read, and a
`filename*` carrying the real UTF-8 name for every client written this century.
Browsers prefer `filename*`, so the user still gets "Yıldız Tekstil".
"""
from __future__ import annotations

from urllib.parse import quote

# Turkish letters that latin-1 cannot carry, plus the ones it can — all folded,
# so the ASCII fallback reads as a name rather than as damage.
_TR_ASCII = str.maketrans({
    "ı": "i", "İ": "I", "ğ": "g", "Ğ": "G", "ş": "s", "Ş": "S",
    "ö": "o", "Ö": "O", "ü": "u", "Ü": "U", "ç": "c", "Ç": "C",
    # A lowercased "İ" is "i" plus a combining dot above, and that dot is not
    # latin-1 either. It is invisible in a filename and worth nothing.
    "̇": "",
})


def ascii_header_value(value: str, *, fallback: str = "") -> str:
    """A header-safe rendering of `value`.

    Turkish letters are folded to their ASCII shape; anything else that latin-1
    cannot carry is dropped. Never raises — a header is not the place to
    discover an encoding problem.
    """
    folded = (value or "").translate(_TR_ASCII)
    cleaned = "".join(c for c in folded if 32 <= ord(c) < 127)
    return cleaned or fallback


def content_disposition(filename: str, *, disposition: str = "attachment") -> str:
    """RFC 6266 Content-Disposition carrying both an ASCII and a UTF-8 filename.

    The ASCII form is the fallback; `filename*` is what a browser actually uses,
    so the file lands with its Turkish name intact.
    """
    ascii_name = ascii_header_value(filename, fallback="download")
    # Quotes and backslashes would end the quoted-string early.
    ascii_name = ascii_name.replace('"', "").replace("\\", "")
    encoded = quote(filename or ascii_name, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"

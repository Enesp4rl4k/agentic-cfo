"""The URL fetcher every WeasyPrint render uses: it fetches nothing.

The HTML of a report is built from strings a company typed (its name, a recommendation, an anomaly
description) and some of them are not escaped. WeasyPrint resolves `<img src>`, `<link>`, `@import`,
`@font-face` and CSS `url()` by fetching, so a company name such as `<img src="http://169.254.169.254/">`
would make the server request that address (SSRF), and `file:///etc/passwd` or a `data:` image of a
format a decoder mishandles would reach the server's disk or an image decoder. A report needs none of
those: it has no remote or packaged assets (no `base_url` is given, fonts are the system's). So every
fetch is refused; WeasyPrint logs it and renders the page without that resource.

WeasyPrint 70 reads attributes off the fetcher (`_fail_on_errors`), so a plain function is not enough:
this is a `URLFetcher` whose `allowed_protocols` is empty and whose `fetch` raises.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def deny_fetcher() -> Any:
    """A fresh fetcher for one `HTML(...)`. Imports weasyprint: call it where `HTML` is imported."""
    from weasyprint import URLFetcher

    class DenyFetcher(URLFetcher):  # type: ignore[misc]
        def fetch(self, url: str, headers: Any = None) -> Any:
            logger.warning("report render: external resource refused (%s)", url.split(":", 1)[0][:20])
            raise ValueError("Raporlarda harici kaynak yüklenmez.")

    return DenyFetcher(allowed_protocols=[], allow_redirects=False)

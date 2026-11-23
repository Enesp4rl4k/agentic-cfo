"""The URL fetcher every WeasyPrint render uses: it fetches nothing.

The HTML of a report is built from strings a company typed (its name, a recommendation, an anomaly
description) and some of them are not escaped. WeasyPrint resolves `<img src>`, `<link>`, `@import`,
`@font-face` and CSS `url()` by fetching, so a company name such as `<img src="http://169.254.169.254/">`
would make the server request that address (SSRF), and `file:///etc/passwd` or a `data:` image of a
format a decoder mishandles would reach the server's disk or an image decoder. A report needs none of
those: it has no remote or packaged assets (no `base_url` is given, fonts are the system's). So every
fetch is refused; WeasyPrint logs it and renders the page without that resource.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def deny_fetch(url: str, *_args: Any, **_kwargs: Any) -> Any:
    logger.warning("report render: external resource refused (%s)", url.split(":", 1)[0][:20])
    raise ValueError("Raporlarda harici kaynak yüklenmez.")

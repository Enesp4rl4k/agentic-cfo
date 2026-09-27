"""A report that cannot be rendered is an error, not an empty PDF with a 200.

The engine answered a template or WeasyPrint failure with a stand-in: a page
holding only the company name, a page reading "WeasyPrint yüklü değil" (even
when it was installed and had failed on this report), or a blank page. The
download looked like it had worked.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

from app.api.reports_pdf import _render
from app.services.pdf import PDFEngine, PDFRenderError


def _sahte_modul(monkeypatch, ad: str, **uyeler) -> None:
    """Stand-in modules, so the test does not depend on the machine's libraries
    (WeasyPrint needs Pango/GObject, which a Windows dev box may lack)."""
    mod = types.ModuleType(ad)
    for k, v in uyeler.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, ad, mod)


def test_a_weasyprint_failure_raises_instead_of_a_stand_in(monkeypatch):
    class Patlayan:
        def __init__(self, *a, **k): ...
        def write_pdf(self):
            raise ValueError("font yok")

    _sahte_modul(monkeypatch, "weasyprint", HTML=Patlayan)
    with pytest.raises(PDFRenderError, match="font yok"):
        PDFEngine()._html_to_pdf("<html><body>x</body></html>")


def test_missing_system_libraries_are_named_not_hidden(monkeypatch):
    """Importing WeasyPrint without Pango raises OSError, not ImportError."""
    import builtins

    gercek = builtins.__import__

    def import_(name, *a, **k):
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return gercek(name, *a, **k)

    monkeypatch.delitem(sys.modules, "weasyprint", raising=False)
    monkeypatch.setattr(builtins, "__import__", import_)
    with pytest.raises(PDFRenderError, match="sistem kütüphaneleri"):
        PDFEngine()._html_to_pdf("<html></html>")


def test_a_template_failure_raises_instead_of_a_title_page(monkeypatch):
    class BozukSablon:
        def __init__(self, *a, **k): ...
        def render(self, **k):
            raise KeyError("rapor alanı yok")

    _sahte_modul(monkeypatch, "jinja2", Template=BozukSablon)
    with pytest.raises(PDFRenderError, match="şablonu"):
        PDFEngine()._render_html("cfo_summary", {"company_name": "Kobi"})


async def test_the_route_turns_it_into_a_503_that_says_why():
    async def patlayan() -> bytes:
        raise PDFRenderError("PDF oluşturulamadı: font yok")

    with pytest.raises(HTTPException) as exc:
        await _render(patlayan())
    assert exc.value.status_code == 503
    assert "font yok" in exc.value.detail


async def test_a_good_render_passes_through():
    async def iyi() -> bytes:
        return b"%PDF-1.7 ..."

    assert await _render(iyi()) == b"%PDF-1.7 ..."

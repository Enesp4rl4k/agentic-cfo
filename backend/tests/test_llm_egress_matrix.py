"""THE PROOF: every place in the product that sends to a language model, run with canary data.

For each call site found by AST (`llm_egress_discovery`), its driver (in `tests/llm_egress_sites_*.py`) runs the
REAL agent code against a recording fake provider that sits behind the gateways, three times:

  masked  nothing recorded contains a canary: no known IBAN, TCKN, VKN, card, phone, e-mail, no counterparty,
          vendor, company, member or accountant name (any casing, spacing or diacritics)
  raw     the canary DOES reach the provider (otherwise the masked assertion proves nothing: the driver never
          put tenant data into the prompt); skipped only for a site declared `carries=False` with its reason
  off     the provider is never called, and the site degrades instead of failing

A call site without a driver, or a driver for a site that is gone, fails by name.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from app.platform.llm_egress import dictionary, policy
from tests import llm_egress_sites_core
from tests.llm_egress_discovery import discover
from tests.llm_egress_harness import Recorder, Site, leaked_in, open_world


def _load() -> tuple[dict[str, Site], dict[str, str]]:
    sites: dict[str, Site] = {}
    aliased: dict[str, str] = {}
    here = Path(__file__).parent
    for info in pkgutil.iter_modules([str(here)]):
        if not info.name.startswith("llm_egress_sites_"):
            continue
        module = importlib.import_module(f"tests.{info.name}")
        for site, driver in module.SITES.items():
            assert site not in sites, f"{site} has two drivers"
            sites[site] = driver
        aliased.update(getattr(module, "ALIASED", {}))
    return sites, aliased


SITES, ALIASED = _load()
assert llm_egress_sites_core  # the core file must exist; the others are optional parts of the same registry


def test_every_call_site_has_a_driver_and_every_driver_a_call_site() -> None:
    found = set(discover())
    covered = set(SITES) | set(ALIASED)
    assert found - covered == set(), f"call sites without a canary driver: {sorted(found - covered)}"
    assert covered - found == set(), f"drivers for call sites that no longer exist: {sorted(covered - found)}"
    assert not set(SITES) & set(ALIASED)


def test_an_alias_says_why_it_needs_no_driver_of_its_own() -> None:
    for site, reason in ALIASED.items():
        assert len(reason) > 25 and "::" in reason, f"{site}: name the site that covers it, and how"
        assert reason.split("covered by ")[1].split(" ")[0] in SITES, f"{site}: the covering site has no driver"


def test_the_inventory_is_the_size_the_review_found() -> None:
    assert len(discover()) >= 40  # ~40 agent modules call the gateway: a collapse here means discovery broke


@pytest.mark.parametrize("site", sorted(SITES))
async def test_site(site: str, monkeypatch) -> None:
    spec = SITES[site]

    # masked: no canary may leave
    async with open_world(monkeypatch, Recorder(reply=spec.reply or Recorder().reply, structured=spec.structured)) as env:
        await spec.driver(env)
        assert env.rec.count() >= 1, f"{site}: the driver never reached the provider (an exception was swallowed?)"
        assert leaked_in(env.rec.text()) == [], f"{site}: canary values left in masked mode: {leaked_in(env.rec.text())}"

    # raw: the same run carries the canary, so the assertion above was not vacuous
    async with open_world(monkeypatch, Recorder(reply=spec.reply or Recorder().reply, structured=spec.structured),
                          mode="raw") as env:
        await spec.driver(env)
        if spec.carries:
            assert leaked_in(env.rec.text()), f"{site}: raw mode did not carry the canary: the driver proves nothing"
        else:
            assert spec.note, f"{site}: carries=False needs a note saying why no tenant text reaches this prompt"

    # off: nothing is sent, and the site degrades
    async with open_world(monkeypatch, Recorder(reply=spec.reply or Recorder().reply, structured=spec.structured),
                          mode="off") as env:
        raised: Exception | None = None
        try:
            await spec.driver(env)
        except Exception as exc:
            raised = exc
        if raised is not None:
            from app.platform.model_gateway import LLMUnavailable

            assert spec.off_raises and isinstance(raised, LLMUnavailable), f"{site}: off mode broke the site: {raised!r}"
        else:
            assert not spec.off_raises, f"{site}: declared off_raises but it degrades without raising: drop the flag"
        assert env.rec.count() == 0, f"{site}: a call was made with LLM_DATA_MODE=off"


def test_caches_are_clean_after_the_matrix() -> None:
    policy._CHOICES.clear()
    dictionary.forget()

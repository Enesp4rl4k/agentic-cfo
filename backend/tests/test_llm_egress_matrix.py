"""THE PROOF: every place in the product that sends to a language model, run with canary data, through the
entry points the app really uses (`tests/llm_egress_entries.py`), with the context the app really has.

For each call site found by AST (`llm_egress_discovery`), its driver (in `tests/llm_egress_sites_*.py`) runs the
REAL agent code against a recording fake provider that sits behind the gateways:

  masked, per entry  through EACH real entry point the site has: the provider is reached (so the company was
                     known there: masked mode fails closed otherwise) and nothing recorded contains a canary: no
                     IBAN (any spelling), TCKN, VKN, card, phone, e-mail (IDN too), no counterparty, vendor,
                     company, member or accountant name, not with a suffix, a line break, upper case, nor a
                     surname or first name alone
  raw                the canary DOES reach the provider (otherwise the masked assertion proves nothing);
                     skipped only for a site declared `carries=False` with its reason
  off                the provider is never called, and the site degrades instead of failing
  no context         the site run with NO company context (what a forgotten entry point would give): masked
                     mode refuses, nothing is sent, the refusal is counted, the site degrades
  dictionary down    (representative sites) the names cannot be read: refused, nothing sent

The tenant context is never set by this file: a site the app reaches without a company fails here by name.
A call site without a driver or without declared entry points, or a driver for a site that is gone, fails by name.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from app.platform.llm_egress import dictionary, policy, refusals
from tests import llm_egress_sites_core
from tests.llm_egress_discovery import discover
from tests.llm_egress_entries import SITE_ENTRIES, run_entry
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

# One site per kind of entry point, for the dictionary-failure run.
DICTIONARY_DOWN = (
    "agents/chat_agent.py::chat_with_cfo", "agents/anomaly_agent.py::_generate_anomaly_narrative",
    "agents/risk/orchestrator.py::node_risk_summary", "agents/ceo/okr_agent.py::_generate_okr_narrative",
    "api/ws_stream.py::_stream_llm_tokens", "services/rag_service.py::index_job_text",
    "scheduler.py::_generate_morning_brief_for_org",
)


def _recorder(spec: Site) -> Recorder:
    return Recorder(reply=spec.reply or Recorder().reply, structured=spec.structured)


def test_every_call_site_has_a_driver_and_every_driver_a_call_site() -> None:
    found = set(discover())
    covered = set(SITES) | set(ALIASED)
    assert found - covered == set(), f"call sites without a canary driver: {sorted(found - covered)}"
    assert covered - found == set(), f"drivers for call sites that no longer exist: {sorted(covered - found)}"
    assert not set(SITES) & set(ALIASED)


def test_every_driven_site_declares_its_real_entry_points() -> None:
    assert set(SITE_ENTRIES) == set(SITES), (
        f"entry points missing: {sorted(set(SITES) - set(SITE_ENTRIES))}; "
        f"stale: {sorted(set(SITE_ENTRIES) - set(SITES))}"
    )


def test_an_alias_says_why_it_needs_no_driver_of_its_own() -> None:
    for site, reason in ALIASED.items():
        assert len(reason) > 25 and "::" in reason, f"{site}: name the site that covers it, and how"
        assert reason.split("covered by ")[1].split(" ")[0] in SITES, f"{site}: the covering site has no driver"


def test_the_inventory_is_the_size_the_review_found() -> None:
    assert len(discover()) >= 40  # ~40 agent modules call the gateway: a collapse here means discovery broke


async def _run(spec: Site, entry: str | None, env, monkeypatch) -> Exception | None:
    try:
        if entry is None:
            await spec.driver(env)
        else:
            await run_entry(entry, env, spec.driver, monkeypatch)
    except Exception as exc:
        return exc
    return None


def _degrades(site: str, spec: Site, raised: Exception | None) -> None:
    if raised is None:
        return
    from app.platform.model_gateway import LLMUnavailable

    assert spec.off_raises and isinstance(raised, LLMUnavailable), f"{site}: the site broke instead of degrading: {raised!r}"


@pytest.mark.parametrize("site", sorted(SITES))
async def test_site(site: str, monkeypatch) -> None:
    spec, entries = SITES[site], SITE_ENTRIES[site]

    # masked, through every real entry point: the company is known there, and no canary leaves
    for entry in entries:
        async with open_world(monkeypatch, _recorder(spec)) as env:
            raised = await _run(spec, entry, env, monkeypatch)
            assert raised is None, f"{site} via {entry}: {raised!r}"
            assert refusals.counts() == dict.fromkeys(refusals.REASONS, 0), (
                f"{site} via {entry}: masked mode refused: the app reaches this site WITHOUT a company ({refusals.counts()})"
            )
            assert env.rec.count() >= 1, f"{site} via {entry}: the driver never reached the provider"
            leaks = leaked_in(env.rec.text())
            assert leaks == [], f"{site} via {entry}: canary values left in masked mode: {leaks}"

    # raw: the same run carries the canary, so the assertion above was not vacuous
    async with open_world(monkeypatch, _recorder(spec), mode="raw") as env:
        raised = await _run(spec, entries[0], env, monkeypatch)
        assert raised is None, f"{site} raw: {raised!r}"
        if spec.carries:
            assert leaked_in(env.rec.text()), f"{site}: raw mode did not carry the canary: the driver proves nothing"
        else:
            assert spec.note, f"{site}: carries=False needs a note saying why no tenant text reaches this prompt"

    # off: nothing is sent, and the site degrades
    async with open_world(monkeypatch, _recorder(spec), mode="off") as env:
        raised = await _run(spec, entries[0], env, monkeypatch)
        if raised is None:
            assert not spec.off_raises or entries[0] == "ws", f"{site}: declared off_raises but it degrades: drop the flag"
        _degrades(site, spec, raised)
        assert env.rec.count() == 0, f"{site}: a call was made with LLM_DATA_MODE=off"

    # no company context at all (a forgotten entry point): masked mode refuses, nothing leaves, it is counted
    if entries != ("explicit",):
        async with open_world(monkeypatch, _recorder(spec)) as env:
            raised = await (_run(spec, "ws", env, monkeypatch) if entries == ("ws",) else _run(spec, None, env, monkeypatch))
            if entries != ("ws",):  # the WebSocket handler sets its own context: covered by its entry run above
                _degrades(site, spec, raised)
                assert env.rec.count() == 0, f"{site}: sent without a company in masked mode"
                assert refusals.counts()["no_organisation_context"] >= 1, f"{site}: no refusal recorded (silently skipped?)"


@pytest.mark.parametrize("site", DICTIONARY_DOWN)
async def test_masked_mode_refuses_when_the_names_cannot_be_read(site: str, monkeypatch) -> None:
    from app.platform.llm_egress.dictionary import LoadedDictionary
    from app.platform.llm_egress.names import NameDictionary

    spec = SITES[site]

    async def broken(org_id: str) -> LoadedDictionary:
        return LoadedDictionary(NameDictionary(), complete=False)  # a source failed to read

    async with open_world(monkeypatch, _recorder(spec)) as env:
        monkeypatch.setattr(dictionary, "_load", broken)
        raised = await _run(spec, SITE_ENTRIES[site][0], env, monkeypatch)
        _degrades(site, spec, raised)
        assert env.rec.count() == 0, f"{site}: sent with an incomplete names dictionary"
        assert refusals.counts()["dictionary_unavailable"] >= 1


def test_caches_are_clean_after_the_matrix() -> None:
    policy._CHOICES.clear()
    dictionary.forget()
    refusals.reset()

"""Harness for the LLM egress proof: canary values, a recording fake provider, and a seeded company.

The fake provider replaces ONLY what is behind the gateways: the chat client `model_gateway._build_client`
returns and `embedding_gateway._client_embed`. Everything in front of it (agents, `complete_text`, the
session, masking) is the real code, so what the recorder holds is exactly what would have left the process.

Canaries are distinctive values no product text contains by accident. A site (an agent function that calls the
gateway) is proven when, in `masked` mode, none of them appears in anything recorded, AND in `raw` mode the
same run does carry them (otherwise the masked assertion would be vacuous: the fixture never reached the prompt).
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any


def _iban(bban: str, country: str = "TR") -> str:
    check = 98 - int("".join(str(int(c, 36)) for c in bban + country + "00")) % 97
    return f"{country}{check:02d}{bban}"


def _vkn(prefix9: str) -> str:
    from app.platform.llm_egress.detectors import vkn_ok

    return next(prefix9 + str(c) for c in range(10) if vkn_ok(prefix9 + str(c)))


IBAN = _iban("0006200000000000009917")
VKN = _vkn("729104538")

CANARY = SimpleNamespace(
    iban=IBAN,
    iban_spaced=" ".join(IBAN[i:i + 4] for i in range(0, len(IBAN), 4)),
    tckn="10000000146",
    vkn=VKN,
    pan="4111 1111 1111 1111",
    phone="0532 987 65 43",
    email="karvesta.muhasebe@zemtrak-nakliyat.example",
    company="Velorin Tekstil Sanayi A.Ş.",
    company_short="Velorin Tekstil",
    counterparty="Karvesta Yapı Malzemeleri A.Ş.",
    counterparty_short="Karvesta Yapı Malzemeleri",
    vendor="Zemtrak Nakliyat Ltd. Şti.",
    vendor_short="Zemtrak Nakliyat",
    person="Selin Aksoy",
    accountant="Murat Demirtaş",
)
CANARY.email_idn = "muhasebe@ışıkgıda.com.tr"
CANARY.surname, CANARY.first_name = "Aksoy", "Selin"
# What must never appear in a masked payload (compared case- and diacritic-insensitively, spaces collapsed).
LEAK_VALUES = (
    CANARY.iban, CANARY.iban_spaced, CANARY.iban[2:], CANARY.tckn, CANARY.vkn, CANARY.pan, CANARY.phone, CANARY.email,
    CANARY.email_idn, CANARY.company_short, CANARY.counterparty_short, CANARY.vendor_short, CANARY.person,
    CANARY.accountant, CANARY.surname, CANARY.first_name,
)
# Every spelling the review found leaking: a suffix with no apostrophe, a line break or extra spaces inside a
# name, upper case, a surname or first name alone, an IBAN with dashes / a line break / lower case / no "TR"
# (labelled), an e-mail with a non-ASCII domain.
VARIANTS = (
    f"{CANARY.counterparty_short}ye fatura; KARVESTA\n YAPI   MALZEMELERİ ödemesi; {CANARY.vendor_short}ın faturası, "
    f"VELORİN   TEKSTİLİN payı; {CANARY.surname}'un ve {CANARY.surname}un onayı, dün {CANARY.first_name} aradı; "
    f"Murat\nDemirtaş notu; IBAN: {' '.join(CANARY.iban[2:][i:i + 4] for i in range(0, 24, 4))}; "
    f"iban {CANARY.iban.lower()}; IBAN {'-'.join(CANARY.iban[i:i + 4] for i in range(0, 26, 4))}; "
    f"{CANARY.iban[:12]}\n{CANARY.iban[12:]}; {CANARY.email_idn}; Tel: 0532-987-65-43; "
    # the final review's three leaks: a name hyphenated across a line break, a labelled TCKN written in groups,
    # a first name with a Cyrillic look-alike letter (е, U+0435)
    f"Karv-\nesta Yapı Malzemeleri hesabı; Kimlik: {CANARY.tckn[:3]} {CANARY.tckn[3:6]} {CANARY.tckn[6:9]} "
    f"{CANARY.tckn[9:]}; onaylayan Sеlin {CANARY.surname} imzası; "  # (repeated texts must not glue words)
)
# A free-text description that carries identifiers and names: what a bank statement line really looks like.
DESCRIPTION = (
    f"FAST {CANARY.counterparty} IBAN {CANARY.iban_spaced} fatura ödemesi; ilgili {CANARY.person}, "
    f"tel {CANARY.phone}, {CANARY.email}. {VARIANTS}"
)


def normalise(text: str) -> str:
    """Folded for comparison the way a reader sees it: a hyphen at a line break joins the word, and a Cyrillic or
    Greek look-alike letter reads as its Latin twin (so a leak spelled that way is still caught as a leak)."""
    import re

    from app.platform.llm_egress.names import _CONFUSABLE, fold

    joined = re.sub(r"[-‐‑][ \t]*\r?\n[ \t]*", "", text)
    return " ".join(fold("".join(_CONFUSABLE.get(c, c) for c in joined)).split())


def leaked_in(text: str) -> list[str]:
    """Canary values present in `text`, however they are cased, spaced or accented."""
    hay = normalise(text)
    hay_compact = hay.replace(" ", "")
    return [v for v in LEAK_VALUES if normalise(v) in hay or normalise(v).replace(" ", "") in hay_compact]


@dataclass
class Sent:
    kind: str                 # "chat" | "stream" | "embed"
    texts: list[str]


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata: dict[str, int] = {}

    def __str__(self) -> str:
        return self.content


@dataclass
class Recorder:
    """What the provider would have received, and what it answers."""

    sent: list[Sent] = field(default_factory=list)
    reply: str | Callable[[list[str]], str] = "Kısa bir özet: veriler tutarlı görünüyor."
    structured: Callable[[type], Any] | None = None
    method: str | None = None  # how the gateway asked for structured output

    def text(self) -> str:
        return "\n".join(t for s in self.sent for t in s.texts)

    def count(self, kind: str | None = None) -> int:
        return sum(1 for s in self.sent if kind is None or s.kind == kind)

    def answer(self, texts: list[str]) -> str:
        return self.reply(texts) if callable(self.reply) else self.reply


class FakeChat:
    """The client `_build_client` returns: records every send, answers from the Recorder."""

    def __init__(self, rec: Recorder) -> None:
        self.rec = rec
        self._schema: type | None = None

    @staticmethod
    def _texts(messages: list[Any]) -> list[str]:
        return [str(getattr(m, "content", m)) for m in messages]

    async def ainvoke(self, messages: list[Any]) -> Any:
        texts = self._texts(messages)
        self.rec.sent.append(Sent("chat", texts))
        if self._schema is not None:
            if self.rec.structured is None:
                raise AssertionError("this site calls a structured output; give the Recorder a `structured` factory")
            return self.rec.structured(self._schema)
        return _Msg(self.rec.answer(texts))

    async def astream(self, messages: list[Any]):
        texts = self._texts(messages)
        self.rec.sent.append(Sent("stream", texts))
        answer = self.rec.answer(texts)
        for i in range(0, len(answer), 7):  # small chunks: a placeholder is often split across two
            yield _Msg(answer[i:i + 7])

    def with_structured_output(self, schema: type, **kwargs: Any) -> FakeChat:
        self.rec.method = kwargs.get("method")  # the gateway asks for "function_calling" (the wire format)
        self._schema = schema
        return self


def install(monkeypatch, rec: Recorder, *, mode: str = "masked", document_text: str = "allow") -> None:
    """Point the gateways at the recorder and set the data mode. No provider is ever contacted."""
    from app.config import get_settings
    from app.platform import embedding_gateway
    from app.platform import model_gateway as mg

    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "sk-recording-fake-not-a-secret")
    monkeypatch.setattr(settings, "llm_data_mode", mode)
    monkeypatch.setattr(settings, "llm_document_text", document_text)
    monkeypatch.setattr(settings, "rag_embedding_enabled", True)
    monkeypatch.setattr(mg, "_build_client", lambda cfg, temperature, max_tokens: FakeChat(rec))
    monkeypatch.setattr(mg, "_persist_call_log", lambda **_: None)

    def fake_embed(texts: list[str]) -> list[list[float]]:
        rec.sent.append(Sent("embed", list(texts)))
        return [[float(len(t) % 7), 0.5, 0.25] for t in texts]

    monkeypatch.setattr(embedding_gateway, "_client_embed", fake_embed)


async def seed_company(maker) -> str:
    """A company whose books hold every canary: returns the organisation id."""
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.canonical_transaction import CanonicalTransaction
    from app.models.open_item import OpenItem
    from app.models.organization import Organization, OrgMembership
    from app.models.related_party import RelatedParty
    from app.models.transaction import Transaction
    from app.models.user import User

    async with maker() as db:
        org = Organization(name=CANARY.company, slug="velorin-tekstil", legal_title=CANARY.company, vkn=CANARY.vkn,
                           country_code="TR", base_currency="TRY", locale="tr-TR")
        db.add(org)
        await db.flush()
        owner = User(email="sahip@velorin.example", hashed_password="x", full_name=CANARY.person, org_id=org.id,
                     role="owner", email_verified_at=datetime.now(UTC))
        smmm = User(email="mm@velorin.example", hashed_password="x", full_name=CANARY.accountant, role="smmm")
        db.add_all([owner, smmm])
        await db.flush()
        db.add(OrgMembership(user_id=smmm.id, org_id=org.id, role="smmm"))
        job = AnalysisJob(status=JobStatus.COMPLETED, filename="ekstre.csv", file_path="ekstre.csv", file_type="csv",
                          org_id=str(org.id), user_id=str(owner.id))
        db.add(job)
        await db.flush()
        db.add(Transaction(job_id=str(job.id), amount_kurus=1_234_567_89, type="expense", category="other_expense",
                           description=DESCRIPTION, vendor=CANARY.vendor, counterparty=CANARY.counterparty,
                           transaction_date=datetime(2026, 3, 15, tzinfo=UTC), raw_text=DESCRIPTION))
        db.add(CanonicalTransaction(org_id=str(org.id), source_type="upload", source_record_id="t1",
                                    transaction_date=datetime(2026, 3, 15, tzinfo=UTC), amount_cents=1_234_567_89,
                                    currency="TRY", direction="expense", counterparty=CANARY.counterparty,
                                    description=DESCRIPTION))
        db.add(OpenItem(org_id=str(org.id), direction="payable", instrument="invoice", document_id="inv:b:k:1",
                        counterparty=CANARY.vendor, amount_cents=500_000, issue_date=date(2026, 3, 1)))
        db.add(RelatedParty(org_id=str(org.id), name=CANARY.counterparty, normalized_name="karvesta",
                            relationship_type="diger", tax_id=CANARY.vkn))
        await db.commit()
        return str(org.id)


@dataclass
class SiteEnv:
    """What a site driver gets: the company, the recorder, and a sessionmaker on the seeded database."""

    org_id: str
    rec: Recorder
    maker: Any
    canary: SimpleNamespace = field(default_factory=lambda: CANARY)
    description: str = DESCRIPTION

    def figures(self) -> dict[str, Any]:
        """A dashboard-shaped dict that names the company and its counterparties (what narratives are built from)."""
        return {
            "company_name": CANARY.company, "top_vendors": [{"vendor": CANARY.vendor, "total": 1_234_567.89}],
            "net_cash": 1_234_567.89,
        }


@dataclass(frozen=True)
class Site:
    """An agent function that calls the gateway, and how to run it with canary-bearing input."""

    driver: Callable[[SiteEnv], Awaitable[Any]]
    carries: bool = True       # False: by design no tenant text reaches this prompt; say why in `note`
    note: str = ""
    structured: Callable[[type], Any] | None = None  # answer for a structured-output site
    reply: str | Callable[[list[str]], str] | None = None  # the provider's text answer, when the site parses it
    off_raises: bool = False   # True: with `off` the site's own contract is to raise LLMUnavailable (say why in `note`)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@asynccontextmanager
async def open_world(monkeypatch, rec: Recorder | None = None, *, mode: str = "masked",
                     document_text: str = "allow", tenant: bool = False) -> AsyncIterator[SiteEnv]:
    """A seeded company on a throwaway database, the recorder behind the gateways.

    The tenant context is NOT set (tenant=False, the default): the code under test must get it the way the
    app does (`tests/llm_egress_entries.py` runs each site through its real entry point). tenant=True is for
    unit tests of the gateway itself. Use it INSIDE the test body: the context is a contextvar."""
    from app import database
    from app.core.tenancy import set_current_tenant
    from app.platform.llm_egress import dictionary, policy, refusals
    from tests.db_helpers import gecici_veritabani

    rec = rec or Recorder()
    async with gecici_veritabani() as maker:
        monkeypatch.setattr(database, "session_factory", lambda: maker)
        policy._CHOICES.clear()
        dictionary.forget()
        refusals.reset()
        set_current_tenant(None)
        org_id = await seed_company(maker)
        install(monkeypatch, rec, mode=mode, document_text=document_text)
        if tenant:
            set_current_tenant(org_id)
        try:
            yield SiteEnv(org_id=org_id, rec=rec, maker=maker)
        finally:
            set_current_tenant(None)
            policy._CHOICES.clear()
            dictionary.forget()
            refusals.reset()

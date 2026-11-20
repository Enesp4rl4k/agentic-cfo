"""SMMM agent: what the accountant corrects, the agent remembers.

Until now a corrected account fed only the confidence calibration. The same
vendor came back next month classified by the same keyword, wrong the same way,
and the accountant corrected it again.

Rules held here:
* one correction is not a rule (it could be a one-off); two consistent ones are;
* a conflicting correction switches the rule off rather than picking a side;
* a learned rule is a *suggestion with a measured track record*: its level has no
  corpus measurement, so until the organisation has enough of its own decisions
  the entry is still held for review - but with the account already filled in;
* only a person's single correction teaches; a bulk approval never does;
* one organisation's rules are never used for another's;
* the source's own account still wins over a learned rule.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.agents.accounting.orchestrator import get_muhasebe_agent
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.accounting.ogrenilmis_kural import (
    anahtar_uret,
    kurallari_yukle,
    ogren,
)
from tests.api_helpers import kullanici

# ── the key ──────────────────────────────────────────────────────────────────

def test_the_key_ignores_what_changes_every_month():
    a = anahtar_uret("Kira ödemesi Ocak 2026 - ABC Gayrimenkul 15.01.2026 No:123")
    b = anahtar_uret("KİRA ÖDEMESİ Şubat 2026 - ABC Gayrimenkul 15.02.2026 No:456")
    assert a and a == b


def test_a_vendor_beats_the_description_and_a_generic_text_gives_no_key():
    assert anahtar_uret("havale", vendor="Kaya Gıda A.Ş.") == anahtar_uret("eft 2", vendor="kaya gida a.s.")
    assert anahtar_uret("12345 01.01.2026") == ""  # nothing left to recognise it by
    assert anahtar_uret("") == ""


# ── learning ─────────────────────────────────────────────────────────────────

async def _org(client, email):
    _h, org, uid = await kullanici(client, email, role="owner")
    return org, uid


@pytest.mark.asyncio
async def test_one_correction_is_not_a_rule_two_are(client):
    org, _ = await _org(client, "a@x.com")
    async with client._maker() as db:
        await ogren(db, org, "Reklam gideri Meta", None, "760")
        assert await kurallari_yukle(db, org) == {}
        await ogren(db, org, "Reklam gideri Meta", None, "760")
        rules = await kurallari_yukle(db, org)
    (k,) = rules.values()
    assert k.hesap_kodu == "760" and k.onay_sayisi == 2


@pytest.mark.asyncio
async def test_a_conflicting_correction_switches_the_rule_off(client):
    org, _ = await _org(client, "b@x.com")
    async with client._maker() as db:
        for _ in range(2):
            await ogren(db, org, "Danışmanlık hizmeti Demir", None, "770")
        assert len(await kurallari_yukle(db, org)) == 1
        await ogren(db, org, "Danışmanlık hizmeti Demir", None, "750")
        await ogren(db, org, "Danışmanlık hizmeti Demir", None, "750")
        # 770 x2 against 750 x2: no side is picked.
        assert await kurallari_yukle(db, org) == {}


@pytest.mark.asyncio
async def test_rules_belong_to_one_organisation(client):
    a, _ = await _org(client, "c@x.com")
    b, _ = await _org(client, "d@x.com")
    async with client._maker() as db:
        for _ in range(2):
            await ogren(db, a, "Kargo gideri Yurtiçi", None, "760")
        assert len(await kurallari_yukle(db, a)) == 1
        assert await kurallari_yukle(db, b) == {}


# ── the agent uses them ──────────────────────────────────────────────────────

def _tx(desc="Reklam gideri Meta", **extra):
    return {"id": "t1", "amount_kurus": 50_000, "type": "expense", "description": desc,
            "transaction_date": "2026-01-05T00:00:00+00:00", **extra}


async def _run(rules, tx):
    agent = get_muhasebe_agent(use_llm_fallback=False, regional_packs=["tr"])
    r = await agent.run("j", [tx], kurum_kurallari=rules)
    return r.yevmiye_kayitlari[0]


@pytest.mark.asyncio
async def test_a_learned_account_is_used_and_labelled_and_still_held(client):
    org, _ = await _org(client, "e@x.com")
    async with client._maker() as db:
        for _ in range(2):
            await ogren(db, org, "Reklam gideri Meta", None, "760")
        rules = await kurallari_yukle(db, org)

    e = await _run(rules, _tx("Reklam gideri Meta Ocak"))
    assert e["thp_hesap_kodu"] == "760"
    assert e["guven"]["seviye"] == "ogrenilmis"
    assert "önceki" in e["guven"]["kanit"]
    # No measurement yet for this level: held for review, account already filled.
    assert e["onay_gerekli"] is True
    assert e["guven"]["kaynak"] == "olculmedi"


@pytest.mark.asyncio
async def test_without_a_rule_the_agent_is_unchanged(client):
    with_rule = await _run({}, _tx("Reklam gideri Meta"))
    assert with_rule["guven"]["seviye"] != "ogrenilmis"


@pytest.mark.asyncio
async def test_the_sources_own_account_beats_a_learned_rule(client):
    org, _ = await _org(client, "f@x.com")
    async with client._maker() as db:
        for _ in range(2):
            await ogren(db, org, "Reklam gideri Meta", None, "760")
        rules = await kurallari_yukle(db, org)
    e = await _run(rules, _tx("Reklam gideri Meta", account_code="770"))
    assert e["thp_hesap_kodu"] == "770" and e["guven"]["seviye"] == "kaynak_hesap"


# ── through the correction route ─────────────────────────────────────────────

P = "/api/v1/smmm/onay"


async def _queue(client, email, descs):
    h, org, uid = await kullanici(client, email, role="owner")
    async with client._maker() as db:
        (await db.get(Organization, org)).regional_packs = ["tr"]
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                          org_id=org, user_id=uid, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        ids = []
        for n, d in enumerate(descs):
            row = SMMMOnayKaydi(job_id=job.id, org_id=org, kayit_id=f"k{n}", tx_description=d,
                                otomatik_hesap_kodu="770", orijinal_kayit={}, durum=OnayDurumu.BEKLIYOR)
            db.add(row)
            await db.flush()
            ids.append(row.id)
        await db.commit()
    return h, org, ids


@pytest.mark.asyncio
async def test_two_corrections_through_the_route_make_a_rule(client):
    h, org, ids = await _queue(client, "g@x.com", ["Reklam gideri Meta Ocak", "Reklam gideri Meta Şubat"])
    body = {"hesap_kodu": "760", "hesap_adi": "Pazarlama Giderleri"}
    for i in ids:
        assert (await client.post(f"{P}/{i}/duzeltle", json=body, headers=h)).status_code == 200
    async with client._maker() as db:
        rules = await kurallari_yukle(db, org)
    (k,) = rules.values()
    assert k.hesap_kodu == "760"


@pytest.mark.asyncio
async def test_a_bulk_approval_never_teaches(client):
    h, _org, ids = await _queue(client, "h@x.com", ["Kira ödemesi A", "Kira ödemesi A"])
    r = await client.post(f"{P}/toplu-onayla", json={"kayit_idler": ids}, headers=h)
    assert r.json()["data"]["onaylandi_count"] == 2
    async with client._maker() as db:
        from app.models.smmm_hesap_kurali import SMMMHesapKurali

        n = (await db.execute(select(func.count()).select_from(SMMMHesapKurali))).scalar_one()
    assert n == 0

"""E-postayla veri — forward a statement once, and every month it arrives by itself.

GET  /email/ingest-address        the organisation's address, created on first ask
POST /email/ingest-address/yenile replace the address; mail to the old one is refused
GET  /email/history               the mail that arrived, and what became of each file
POST /email/inbound               the mail provider's webhook (public; verifies the secret)

What this replaced never worked. The address was a hash of the organisation id,
stored nowhere and so impossible to change; the receiving endpoint wanted a
logged-in user, which no mail provider is; and each attachment called an upload
service that does not exist, so every one came back "error".

A message's attachments go through the same recognition as a file dropped on
the "Verilerimi Bağla" page: a statement starts an analysis, a staff list
joins the latest one. Nobody is there to answer "which kind is this?", so a
file that needs that answer is recorded as such and not guessed at.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.veri_baglama import Sahip, dosyalari_ekle
from app.config import get_settings
from app.database import get_db
from app.models.email_ingest import EmailIngestAddress, EmailIngestMessage, yeni_kod
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)

_KOD = re.compile(r"veri\+([a-z0-9]{8,32})@", re.IGNORECASE)
_MAX_MIME = 25 * 1024 * 1024
_TEKRAR_BAKILAN = 200          # recent messages checked for a file already received
ONCEDEN_ALINDI = "onceden_alindi"


def _acik() -> bool:
    s = get_settings()
    return bool(s.email_ingest_domain and s.email_inbound_secret)


def _adres(kod: str) -> str:
    return f"veri+{kod}@{get_settings().email_ingest_domain}"


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Kullanıcı bir organizasyona bağlı değil.")
    return str(user.org_id)


async def _aktif_adres(db: AsyncSession, org_id: str) -> EmailIngestAddress | None:
    return (await db.execute(
        select(EmailIngestAddress)
        .where(EmailIngestAddress.org_id == org_id, EmailIngestAddress.revoked_at.is_(None))
        .order_by(desc(EmailIngestAddress.created_at)).limit(1)
    )).scalar_one_or_none()


def _adres_yaniti(adres: EmailIngestAddress | None) -> dict[str, Any]:
    if not _acik():
        return {"acik": False, "adres": None, "mesaj": (
            "Bu sunucuda e-postayla veri alma henüz açılmadı. Dosyalarınızı 'Verilerimi Bağla' "
            "sayfasından yükleyebilirsiniz.")}
    assert adres is not None
    return {
        "acik": True,
        "adres": _adres(adres.kod),
        "olusturuldu": adres.created_at.isoformat() if adres.created_at else None,
        "nasil": [
            "Bankanızın ya da muhasebe programınızın gönderdiği ekstre, fatura veya rapor e-postalarını "
            "bu adrese iletin.",
            "Her ay elle iletmek istemiyorsanız, e-posta programınızda bu gönderenden gelen postaları "
            "bu adrese otomatik ileten bir kural kurun.",
            "Excel, CSV ve PDF ekleri okunur; e-postanın metni okunmaz.",
            "Adresi bilen herkes şirketinize dosya gönderebilir. Başkasıyla paylaşıldıysa 'Adresi yenile' "
            "ile değiştirin; eski adrese gelen posta reddedilir.",
        ],
    }


@router.get("/email/ingest-address")
async def get_ingest_address(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org(current_user)
    adres = None
    if _acik():
        adres = await _aktif_adres(db, org_id)
        if adres is None:
            adres = EmailIngestAddress(org_id=org_id, created_by=str(current_user.id))
            db.add(adres)
            await db.commit()
    return {"data": _adres_yaniti(adres), "error": None}


@router.post("/email/ingest-address/yenile")
async def renew_ingest_address(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org(current_user)
    if not _acik():
        return {"data": _adres_yaniti(None), "error": None}
    eski = await _aktif_adres(db, org_id)
    if eski is not None:
        eski.revoked_at = datetime.now(UTC)
    yeni = EmailIngestAddress(org_id=org_id, created_by=str(current_user.id), kod=yeni_kod())
    db.add(yeni)
    await db.commit()
    return {"data": _adres_yaniti(yeni), "error": None}


@router.get("/email/history")
async def get_email_history(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org(current_user)
    rows = (await db.execute(
        select(EmailIngestMessage).where(EmailIngestMessage.org_id == org_id)
        .order_by(desc(EmailIngestMessage.received_at)).limit(max(1, min(limit, 100)))
    )).scalars().all()
    return {"data": [
        {"id": m.id, "alindi": m.received_at.isoformat() if m.received_at else None,
         "gonderen": m.sender, "konu": m.subject, "dosyalar": m.sonuclar}
        for m in rows
    ], "error": None}


# ── The provider's webhook ──────────────────────────────────────────────────

def _gizli_dogru(request: Request) -> bool:
    beklenen = get_settings().email_inbound_secret
    if not beklenen:
        return False
    verilen = request.headers.get("x-inbound-secret", "")
    auth = request.headers.get("authorization", "")
    if not verilen and auth.lower().startswith("basic "):
        try:
            verilen = base64.b64decode(auth[6:]).decode("utf-8").partition(":")[2]
        except (binascii.Error, UnicodeDecodeError):
            verilen = ""
    return bool(verilen) and hmac.compare_digest(verilen.encode(), beklenen.encode())


async def _mime(request: Request) -> tuple[bytes, list[str]]:
    """The raw message, and any recipient the provider told us outside it."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        form = await request.form()
        alici = [str(form.get(k) or "") for k in ("recipient", "to", "envelope")]
        for alan in ("email", "body-mime"):
            v = form.get(alan)
            if v is None:
                continue
            veri = await v.read() if hasattr(v, "read") else str(v).encode("utf-8")
            return veri, alici
        raise HTTPException(status_code=400, detail="Formda ham e-posta yok (email ya da body-mime alanı).")
    return await request.body(), []


def _kod_bul(parsed: Any, disaridan: list[str], ham: bytes) -> str | None:
    import email

    msg = email.message_from_bytes(ham[:256 * 1024])
    adaylar = [*disaridan, parsed.recipient or ""]
    for h in ("Delivered-To", "X-Original-To", "X-Forwarded-To", "Envelope-To", "To", "Cc"):
        adaylar += [str(v) for v in (msg.get_all(h) or [])]
    for a in adaylar:
        m = _KOD.search(a)
        if m:
            return m.group(1).lower()
    return None


@router.post("/email/inbound")
async def email_inbound(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    # Refused outright without a configured secret: an unset secret is not
    # permission to accept mail from anyone who finds the URL.
    if not _gizli_dogru(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    ham, disaridan = await _mime(request)
    if not ham:
        raise HTTPException(status_code=400, detail="Boş e-posta.")
    if len(ham) > _MAX_MIME:
        raise HTTPException(status_code=413, detail="E-posta 25 MB'tan büyük.")

    from app.services.email_parser import get_email_parser

    parsed = get_email_parser().parse(ham)
    kod = _kod_bul(parsed, disaridan, ham)
    adres = None
    if kod:
        adres = (await db.execute(
            select(EmailIngestAddress).where(EmailIngestAddress.kod == kod)
        )).scalar_one_or_none()
    # A provider retries anything but a success, so mail to an unknown or
    # replaced address is answered 200 and dropped; the answer says nothing
    # about which organisations exist.
    if adres is None or adres.revoked_at is not None:
        logger.info("E-posta alındı ama adres geçerli değil (kod=%s)", "var" if kod else "yok")
        return {"data": {"kabul": False}, "error": None}

    onceki = (await db.execute(
        select(EmailIngestMessage.sonuclar).where(EmailIngestMessage.org_id == adres.org_id)
        .order_by(desc(EmailIngestMessage.received_at)).limit(_TEKRAR_BAKILAN)
    )).scalars().all()
    alinmis = {d.get("sha256") for sonuc in onceki for d in (sonuc or []) if d.get("durum") != "reddedildi"}

    yeni: list[tuple[str, bytes]] = []
    sonuclar: list[dict[str, Any]] = []
    for att in parsed.attachments:
        sha = att.sha256 or hashlib.sha256(att.content).hexdigest()
        if sha in alinmis:
            sonuclar.append({"dosya": att.filename, "sha256": sha, "durum": ONCEDEN_ALINDI,
                             "mesaj": "Bu dosya daha önce alınmış; tekrar eklenmedi."})
            continue
        alinmis.add(sha)
        yeni.append((att.filename, att.content))
    sahalar = {ad: hashlib.sha256(veri).hexdigest() for ad, veri in yeni}

    if yeni:
        out = await dosyalari_ekle(db, Sahip(adres.org_id, adres.created_by), yeni)
        for d in out["dosyalar"]:
            d["sha256"] = sahalar.get(d["dosya"])
            if d.get("durum") == "secim_gerekli":
                d["mesaj"] = (d.get("mesaj") or "") + (
                    " E-postayla gelen dosyanın türü seçilemiyor; 'Verilerimi Bağla' sayfasından yükleyin.")
            sonuclar.append({k: v for k, v in d.items() if k != "tanima"} | {
                "etiket": (d.get("tanima") or {}).get("etiket")})
    if not parsed.attachments:
        sonuclar.append({"dosya": None, "durum": "ek_yok",
                         "mesaj": "E-postada okunabilir ek yok (Excel, CSV ya da PDF)."})

    db.add(EmailIngestMessage(
        org_id=adres.org_id, address_id=adres.id, sender=(parsed.sender or "")[:500],
        subject=(parsed.subject or "")[:500], message_id=(parsed.message_id or None), sonuclar=sonuclar,
    ))
    await db.commit()
    logger.info("E-posta işlendi org=%s ek=%d", adres.org_id, len(parsed.attachments))
    return {"data": {"kabul": True, "dosyalar": len(sonuclar)}, "error": None}

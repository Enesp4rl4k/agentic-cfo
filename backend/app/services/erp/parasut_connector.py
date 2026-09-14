"""Paraşüt — connected by logging in to Paraşüt, nothing else.

It used to ask the person for an OAuth client id and secret, which means
registering a developer application at Paraşüt: not something a small
business owner does. The platform now holds one Paraşüt application
(`PARASUT_CLIENT_ID` / `PARASUT_CLIENT_SECRET`); the person presses
"Paraşüt ile bağlan", logs in at Paraşüt, and comes back connected.

What else was wrong and is not any more:

- Secrets were "encrypted" with a function that fell back to base64 whenever
  ENCRYPTION_KEY was missing or anything raised — plaintext with extra steps.
  They are encrypted with `app.connectors.crypto` now; a legacy base64 value
  is still read, and written back encrypted.
- The OAuth callback wanted a logged-in user, but it is a browser redirect
  from Paraşüt that carries none, so a connection could never complete. The
  callback now proves itself with a signed, expiring state that must also
  match the one stored for that organisation, and is used once.
- Sync and disconnect took any integration id. Callers now pass the row they
  loaded for the caller's organisation.
- A failed pull was recorded as "success, 0 transactions".

Paraşüt's API contract (company-scoped v4 URLs, JSON:API `attributes`, the
`/me` company listing) is written from its public shape and has not been
exercised against a real Paraşüt account here; the parsing is defensive and a
failure is reported, never silently empty.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

PARASUT_OAUTH_BASE = "https://api.parasut.com/oauth"
PARASUT_API_BASE = "https://api.parasut.com/v4"
PARASUT_AUTH_URL = f"{PARASUT_OAUTH_BASE}/authorize"
PARASUT_TOKEN_URL = f"{PARASUT_OAUTH_BASE}/token"

STATE_TTL_SECONDS = 600
# Tests route Paraşüt's side through an httpx.MockTransport.
_transport: httpx.AsyncBaseTransport | None = None
BEKLIYOR = "pending"
FIRMA_SECIMI = "firma_secimi"
AKTIF = "active"


class ParasutAyarlanmadi(RuntimeError):
    """The platform has no Paraşüt application configured."""


def parasut_acik() -> bool:
    s = get_settings()
    return bool(s.parasut_client_id and s.parasut_client_secret)


def redirect_uri() -> str:
    return f"{get_settings().backend_url.rstrip('/')}/api/v1/erp/parasut/callback"


# ── Secrets ─────────────────────────────────────────────────────────────────

def _sifrele(plaintext: str) -> str:
    from app.connectors.crypto import encrypt_secret

    return encrypt_secret(plaintext)


def _coz(ciphertext: str | None) -> str:
    if not ciphertext:
        return ""
    from app.connectors.crypto import decrypt_secret

    try:
        return decrypt_secret(ciphertext)
    except ValueError:
        # Written by the old base64 "encryption"; read once, re-encrypted on the next write.
        try:
            return base64.b64decode(ciphertext.encode()).decode()
        except (ValueError, UnicodeDecodeError):
            logger.warning("Paraşüt secret could not be read")
            return ""


def _config(integration: Any) -> dict[str, Any]:
    raw = _coz(integration.config_enc)
    try:
        cfg = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        cfg = {}
    return cfg if isinstance(cfg, dict) else {}


def _config_yaz(integration: Any, cfg: dict[str, Any]) -> None:
    integration.config_enc = _sifrele(json.dumps(cfg))


# ── State ───────────────────────────────────────────────────────────────────

def _imza(payload: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:40]


def state_uret(org_id: str, user_id: str, nonce: str, now: float | None = None) -> str:
    exp = int((now or time.time()) + STATE_TTL_SECONDS)
    payload = f"{org_id}.{user_id}.{nonce}.{exp}"
    return f"{payload}.{_imza(payload)}"


def state_dogrula(state: str, now: float | None = None) -> tuple[str, str, str]:
    """(org_id, user_id, nonce) from a state this server signed and that has not expired."""
    parts = state.split(".")
    if len(parts) != 5:
        raise ValueError("geçersiz state")
    org_id, user_id, nonce, exp, sig = parts
    if not hmac.compare_digest(sig, _imza(".".join(parts[:4]))):
        raise ValueError("geçersiz state")
    if not exp.isdigit() or int(exp) < (now or time.time()):
        raise ValueError("süresi dolmuş state")
    return org_id, user_id, nonce


# ── Paraşüt's JSON:API ─────────────────────────────────────────────────────

def _attr(item: dict[str, Any], *names: str) -> Any:
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    for n in names:
        v = attrs.get(n)
        if v not in (None, ""):
            return v
    return None


def firmalar_from_me(body: dict[str, Any]) -> list[dict[str, str]]:
    """Companies in a `/me?include=companies` response (JSON:API `included`)."""
    out = []
    for item in body.get("included") or []:
        if isinstance(item, dict) and item.get("type") == "companies" and item.get("id"):
            out.append({"id": str(item["id"]), "ad": str(_attr(item, "name", "legal_name") or item["id"])})
    return out


def islem_from_fatura(item: dict[str, Any], tip: str) -> dict[str, Any] | None:
    """A sales invoice (income) or purchase bill (expense) as a transaction; None when it carries no amount or date."""
    tutar = _attr(item, "gross_total", "net_total", "total_in_currency", "amount")
    tarih = _attr(item, "issue_date", "issued_date", "date")
    try:
        kurus = round(abs(float(tutar)) * 100)
    except (TypeError, ValueError):
        return None
    if not kurus or not tarih:
        return None
    no = _attr(item, "invoice_no", "invoice_number", "invoice_id")
    aciklama = _attr(item, "description") or ("Satış faturası" if tip == "income" else "Gider faturası")
    return {
        "date": str(tarih)[:10], "amount_cents": kurus, "type": tip,
        "description": f"{aciklama}{f' #{no}' if no else ''}"[:500], "source_id": str(item.get("id") or ""),
    }


class ParasutConnector:
    def __init__(self, db: Any, http: httpx.AsyncClient | None = None) -> None:
        self.db = db
        self._http = http

    async def _post(self, url: str, data: dict[str, str]) -> httpx.Response:
        if self._http is not None:
            return await self._http.post(url, data=data)
        async with httpx.AsyncClient(timeout=30, transport=_transport) as c:
            return await c.post(url, data=data)

    async def _get(self, url: str, token: str, params: dict[str, Any] | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self._http is not None:
            return await self._http.get(url, headers=headers, params=params)
        async with httpx.AsyncClient(timeout=30, transport=_transport) as c:
            return await c.get(url, headers=headers, params=params)

    async def _entegrasyon(self, org_id: str) -> Any:
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration

        return (await self.db.execute(
            select(ERPIntegration).where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "parasut")
        )).scalar_one_or_none()

    async def baslat(self, org_id: str, user_id: str) -> str:
        """The Paraşüt login URL for this organisation; stores the state it must come back with."""
        if not parasut_acik():
            raise ParasutAyarlanmadi("Paraşüt bağlantısı bu sunucuda ayarlanmamış.")
        from app.models.erp_integration import ERPIntegration

        integration = await self._entegrasyon(org_id)
        if integration is None:
            integration = ERPIntegration(org_id=org_id, provider="parasut", display_name="Paraşüt", status=BEKLIYOR)
            self.db.add(integration)
        nonce = secrets.token_urlsafe(16).replace(".", "_")
        cfg = _config(integration)
        # A legacy per-organisation application is dropped: the platform's is used.
        cfg = {k: v for k, v in cfg.items() if k not in ("client_id", "client_secret", "redirect_uri")}
        cfg["oauth_nonce"] = nonce
        _config_yaz(integration, cfg)
        if integration.status != AKTIF:
            integration.status = BEKLIYOR
        await self.db.commit()
        params = {
            "client_id": get_settings().parasut_client_id,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "state": state_uret(org_id, user_id, nonce),
        }
        return f"{PARASUT_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def geri_donus(self, code: str, state: str) -> tuple[str, str]:
        """Finish the login: (org_id, status). Raises ValueError for any state that is not this org's current one."""
        org_id, _user_id, nonce = state_dogrula(state)
        integration = await self._entegrasyon(org_id)
        if integration is None:
            raise ValueError("bağlantı bulunamadı")
        cfg = _config(integration)
        if not cfg.get("oauth_nonce") or not hmac.compare_digest(str(cfg["oauth_nonce"]), nonce):
            raise ValueError("geçersiz ya da kullanılmış state")
        cfg.pop("oauth_nonce")        # used once
        _config_yaz(integration, cfg)
        await self.db.commit()

        s = get_settings()
        resp = await self._post(PARASUT_TOKEN_URL, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "client_id": s.parasut_client_id, "client_secret": s.parasut_client_secret,
        })
        if resp.status_code >= 400:
            integration.status, integration.last_error = BEKLIYOR, f"Paraşüt girişi tamamlanamadı ({resp.status_code})."
            await self.db.commit()
            raise ValueError(integration.last_error)
        token = resp.json()
        self._tokenlari_yaz(integration, token)

        firmalar = await self._firmalar(str(token["access_token"]))
        cfg = _config(integration)
        if len(firmalar) == 1:
            cfg["company_id"], integration.display_name = firmalar[0]["id"], f"Paraşüt · {firmalar[0]['ad']}"
            integration.status = AKTIF
        else:
            # Several companies, or none listed: the person says which.
            cfg["firmalar"] = firmalar
            integration.status = FIRMA_SECIMI
        _config_yaz(integration, cfg)
        integration.connected_at, integration.last_error = datetime.now(UTC), None
        await self.db.commit()
        return org_id, integration.status

    async def _firmalar(self, access_token: str) -> list[dict[str, str]]:
        try:
            resp = await self._get(f"{PARASUT_API_BASE}/me", access_token, {"include": "companies"})
            if resp.status_code >= 400:
                logger.warning("Paraşüt /me %s", resp.status_code)
                return []
            return firmalar_from_me(resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Paraşüt firma listesi alınamadı: %s", exc)
            return []

    def _tokenlari_yaz(self, integration: Any, token: dict[str, Any]) -> None:
        integration.access_token_enc = _sifrele(str(token["access_token"]))
        if token.get("refresh_token"):
            integration.refresh_token_enc = _sifrele(str(token["refresh_token"]))
        integration.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(token.get("expires_in") or 7200))

    @staticmethod
    def secilecek_firmalar(integration: Any) -> list[dict[str, str]]:
        return list(_config(integration).get("firmalar") or []) if integration.status == FIRMA_SECIMI else []

    async def firma_sec(self, integration: Any, company_id: str) -> None:
        cfg = _config(integration)
        secenek = {f["id"]: f["ad"] for f in cfg.get("firmalar") or []}
        if secenek and company_id not in secenek:
            raise ValueError("Bu firma bu Paraşüt hesabında yok.")
        if not company_id.isdigit():
            raise ValueError("Firma numarası rakamlardan oluşur.")
        cfg["company_id"] = company_id
        cfg.pop("firmalar", None)
        _config_yaz(integration, cfg)
        integration.display_name = f"Paraşüt · {secenek.get(company_id, company_id)}"
        integration.status = AKTIF
        await self.db.commit()

    async def _gecerli_token(self, integration: Any) -> str:
        if not integration.is_token_expired():
            return _coz(integration.access_token_enc)
        refresh = _coz(integration.refresh_token_enc)
        s = get_settings()
        if not refresh:
            integration.status = "expired"
            await self.db.commit()
            raise ValueError("Paraşüt oturumu sona erdi; yeniden bağlanın.")
        resp = await self._post(PARASUT_TOKEN_URL, {
            "grant_type": "refresh_token", "refresh_token": refresh,
            "client_id": s.parasut_client_id, "client_secret": s.parasut_client_secret,
        })
        if resp.status_code >= 400:
            integration.status = "expired"
            await self.db.commit()
            raise ValueError("Paraşüt oturumu sona erdi; yeniden bağlanın.")
        self._tokenlari_yaz(integration, resp.json())
        await self.db.commit()
        return _coz(integration.access_token_enc)

    async def islemleri_cek(self, integration: Any, gun: int = 90) -> list[dict[str, Any]]:
        """Sales invoices and purchase bills of the last `gun` days, as transactions. Raises on failure."""
        from app.models.erp_integration import ERPSyncLog

        cfg = _config(integration)
        company_id = str(cfg.get("company_id") or "")
        if integration.status != AKTIF or not company_id:
            raise ValueError("Paraşüt bağlantısı tamamlanmamış.")
        basla = time.time()
        log = ERPSyncLog(integration_id=integration.id, org_id=integration.org_id, provider="parasut",
                         status="running", started_at=datetime.now(UTC))
        self.db.add(log)
        await self.db.commit()
        try:
            token = await self._gecerli_token(integration)
            # Newest first, stopping at the first page that reaches past the
            # window: only JSON:API's own `sort` and `page`, no guessed filter syntax.
            ilk = str(datetime.now(UTC).date() - timedelta(days=gun))
            islemler: list[dict[str, Any]] = []
            for yol, tip in (("sales_invoices", "income"), ("purchase_bills", "expense")):
                sayfa = 1
                while sayfa <= 200:
                    resp = await self._get(f"{PARASUT_API_BASE}/{company_id}/{yol}", token,
                                           {"sort": "-issue_date", "page[size]": 25, "page[number]": sayfa})
                    if resp.status_code >= 400:
                        raise ValueError(f"Paraşüt {yol} isteği başarısız ({resp.status_code}).")
                    data = resp.json().get("data") or []
                    okunan = [t for t in (islem_from_fatura(d, tip) for d in data if isinstance(d, dict)) if t]
                    islemler += [t for t in okunan if t["date"] >= ilk]
                    if len(data) < 25 or any(t["date"] < ilk for t in okunan):
                        break
                    sayfa += 1
            integration.last_sync_status, integration.last_error = "success", None
            integration.last_sync_count = len(islemler)
            log.status, log.transactions_synced = "success", len(islemler)
            return islemler
        except (ValueError, httpx.HTTPError, KeyError) as exc:
            integration.last_sync_status, integration.last_error = "error", str(exc)[:500]
            log.status, log.error_message = "error", str(exc)[:500]
            raise ValueError(str(exc)) from exc
        finally:
            integration.last_sync_at = datetime.now(UTC)
            log.finished_at, log.duration_seconds = datetime.now(UTC), int(time.time() - basla)
            await self.db.commit()

    async def disconnect(self, integration: Any) -> None:
        integration.access_token_enc = None
        integration.refresh_token_enc = None
        integration.status = "disconnected"
        integration.disconnected_at = datetime.now(UTC)
        await self.db.commit()


# ── Pull and analyse (manual and scheduled) ─────────────────────────────────

def islemler_ozeti(islemler: list[dict[str, Any]]) -> str:
    """A fingerprint of a pull: the same invoices give the same value."""
    kanonik = sorted((t["date"], t["type"], t["amount_cents"], t.get("source_id", "")) for t in islemler)
    return hashlib.sha256(json.dumps(kanonik).encode()).hexdigest()


async def parasut_al(db: Any, integration: Any, sahip: Any, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Pull the invoices; open an analysis only when they changed since the last one.

    The same 90 days pulled every day used to become a new analysis every day:
    model cost for an unchanged picture, and an upload counted against the plan
    each time — a free plan's month gone in three days of automation.
    Raises ValueError when the pull fails.
    """
    from app.services.ingest.ekle import islemleri_ekle

    islemler = await ParasutConnector(db, http).islemleri_cek(integration)
    if not islemler:
        return {"durum": "fatura_yok", "sync_count": 0, "job_id": None,
                "mesaj": "Son 90 günde fatura bulunamadı."}
    ozet = islemler_ozeti(islemler)
    cfg = _config(integration)
    if cfg.get("son_ozet") == ozet:
        return {"durum": "degisiklik_yok", "sync_count": len(islemler), "job_id": cfg.get("son_is"),
                "mesaj": "Son alımdan bu yana yeni ya da değişen fatura yok; son analiz güncel."}
    out = await islemleri_ekle(db, sahip, islemler, "parasut")
    if out.get("job_id"):
        cfg = _config(integration)
        cfg["son_ozet"], cfg["son_is"] = ozet, out["job_id"]
        _config_yaz(integration, cfg)
        await db.commit()
    return {"durum": "analiz_baslatildi", "sync_count": len(islemler), "job_id": out.get("job_id"),
            "dosyalar": out.get("dosyalar", [])}

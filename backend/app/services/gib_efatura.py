"""
GİB (Gelir İdaresi Başkanlığı) e-Fatura / e-Arşiv client.

Türkiye'nin elektronik fatura sistemi.
Test ortamı: https://efatura.gib.gov.tr/test

Resmi dokümantasyon:
  https://www.edocument.gov.tr/dosyalar/efatura/kilavuzlar/
  https://www.efatura.gov.tr/efatura-kilavuzlari.html

ÖNEMLİ NOT:
  Production ortamında e-Fatura göndermek için:
  1. GİB e-Fatura mükellefi olunması gerekiyor
  2. Mali mühür veya e-İmza zorunlu
  3. Entegratör lisansı (isteğe bağlı) veya özel entegrasyon

  Test ortamı için bu kısıtlamalar geçerli değildir.
  Bu client test ortamını hedefler.

e-Fatura gelen kutusu, giden fatura listesi ve fatura detaylarını
CFO pipeline'ına entegre eder:
  - Gelen faturalar → gider transaction'ları olarak kaydedilir
  - Giden faturalar → gelir transaction'ları olarak kaydedilir
  - KDV otomatik ayrıştırılır

Bu client aşağıdaki işlemleri yapar:
  1. Gelen fatura listesi çek (inbox)
  2. Giden fatura listesi çek (outbox)
  3. Fatura XML'i parse et → CFO transaction formatına dönüştür
  4. Vergi takvimi oluştur (KDV, Stopaj, Kurumlar Vergisi)
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# GİB test ortamı base URL
GIB_TEST_BASE_URL = "https://efatura.gib.gov.tr/test"
GIB_PROD_BASE_URL = "https://efatura.gib.gov.tr"

# KDV oranları (Türkiye 2024)
KDV_RATES = {
    "standard":  0.20,   # %20 — genel oran (2024'te %18'den artırıldı)
    "reduced_1": 0.10,   # %10 — indirimli oran
    "reduced_2": 0.01,   # %1  — özel indirimli
    "exempt":    0.00,   # %0  — KDV muaf
}


class GIBError(Exception):
    """GİB API hatası."""


class EFaturaClient:
    """
    GİB e-Fatura REST API client.

    Desteklenen işlemler:
      - Gelen/giden fatura listesi
      - Fatura XML parse → transaction dönüşümü
      - Vergi takvimi hesaplama

    Test ortamı sandbox credentials:
      Kullanıcı adı: "test" | Şifre: "test123" (GİB test ortamı)
      Gerçek VKN gerekli değil test için.
    """

    def __init__(
        self,
        vkn: str,          # Vergi Kimlik Numarası
        username: str,
        password: str,
        sandbox: bool = True,
    ) -> None:
        self.vkn      = vkn
        self.username = username
        self.password = password
        self.sandbox  = sandbox
        self.base_url = GIB_TEST_BASE_URL if sandbox else GIB_PROD_BASE_URL
        self._token: str | None = None
        self._http = httpx.AsyncClient(timeout=30.0, verify=not sandbox)

    async def authenticate(self) -> str:
        """
        GİB servisine giriş yap, token al.

        GİB test ortamı Basic Auth kullanır.
        Production ortamı e-İmza veya Mali Mühür gerektirir.
        """
        try:
            resp = await self._http.post(
                f"{self.base_url}/login",
                json={"username": self.username, "password": self.password},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data.get("token") or data.get("access_token", "")
            logger.info("GİB e-Fatura: giriş başarılı (VKN=%s, sandbox=%s)", self.vkn, self.sandbox)
            return self._token
        except httpx.HTTPStatusError as exc:
            raise GIBError(f"GİB giriş hatası: {exc.response.status_code} — {exc.response.text}") from exc
        except Exception as exc:
            raise GIBError(f"GİB bağlantı hatası: {exc}") from exc

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise GIBError("Önce authenticate() çağrılmalı.")
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type":  "application/json",
        }

    async def get_inbox(
        self,
        start_date: str,  # YYYY-MM-DD
        end_date: str,    # YYYY-MM-DD
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Gelen e-fatura listesini çek.

        Her fatura: tedarikçiden alınan gider faturası.
        """
        try:
            resp = await self._http.get(
                f"{self.base_url}/earsiv/documents",
                headers=self._headers(),
                params={
                    "direction": "inbound",
                    "startDate": start_date,
                    "endDate":   end_date,
                    "limit":     limit,
                    "vkn":       self.vkn,
                },
            )
            resp.raise_for_status()
            return self._parse_invoice_list(resp.json(), direction="inbound")
        except httpx.HTTPStatusError as exc:
            raise GIBError(f"Gelen fatura listesi alınamadı: {exc.response.status_code}") from exc

    async def get_outbox(
        self,
        start_date: str,
        end_date: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Giden e-fatura listesini çek.

        Her fatura: müşteriye kesilen satış faturası → gelir.
        """
        try:
            resp = await self._http.get(
                f"{self.base_url}/earsiv/documents",
                headers=self._headers(),
                params={
                    "direction": "outbound",
                    "startDate": start_date,
                    "endDate":   end_date,
                    "limit":     limit,
                    "vkn":       self.vkn,
                },
            )
            resp.raise_for_status()
            return self._parse_invoice_list(resp.json(), direction="outbound")
        except httpx.HTTPStatusError as exc:
            raise GIBError(f"Giden fatura listesi alınamadı: {exc.response.status_code}") from exc

    def _parse_invoice_list(
        self,
        raw: Any,
        direction: str,
    ) -> list[dict[str, Any]]:
        """
        GİB API yanıtını normalize et.

        direction: "inbound" (gider) | "outbound" (gelir)
        """
        items = raw if isinstance(raw, list) else raw.get("documents", raw.get("data", []))
        invoices: list[dict[str, Any]] = []

        for item in items:
            # Fatura tarihi
            raw_date = item.get("issueDate") or item.get("date") or item.get("faturaTarihi", "")
            try:
                if "T" in raw_date:
                    invoice_date = raw_date[:10]
                else:
                    invoice_date = raw_date
            except Exception:
                invoice_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Tutarlar
            net_amount = float(item.get("lineExtensionAmount") or item.get("netAmount") or item.get("matrah", 0) or 0)
            vat_amount = float(item.get("taxAmount") or item.get("kdvTutari", 0) or 0)
            gross_amount = float(item.get("payableAmount") or item.get("toplamTutar", 0) or 0)
            if gross_amount == 0:
                gross_amount = net_amount + vat_amount

            # Karşı taraf
            if direction == "inbound":
                counterparty = (
                    item.get("sellerName") or item.get("tedarikci") or
                    item.get("supplierPartyName", "Bilinmeyen Tedarikçi")
                )
                tx_type = "expense"
            else:
                counterparty = (
                    item.get("buyerName") or item.get("musteri") or
                    item.get("customerPartyName", "Bilinmeyen Müşteri")
                )
                tx_type = "income"

            invoices.append({
                "invoice_id":    item.get("uuid") or item.get("faturaNo") or str(uuid.uuid4()),
                "invoice_number": item.get("invoiceId") or item.get("faturaNo", ""),
                "direction":     direction,
                "date":          invoice_date,
                "net_amount":    net_amount,
                "vat_amount":    vat_amount,
                "gross_amount":  gross_amount,
                "vat_rate":      round(vat_amount / net_amount, 2) if net_amount > 0 else 0.0,
                "currency":      item.get("currency") or item.get("dovizKodu", "TRY"),
                "counterparty":  counterparty,
                "description":   item.get("description") or item.get("aciklama", ""),
                "status":        item.get("status") or item.get("durum", "accepted"),
                "tx_type":       tx_type,
                # CFO pipeline formatına dönüştürülmüş hali
                "amount_cents":  int(gross_amount * 100),
                "transaction_date": invoice_date,
                "vendor":        counterparty if direction == "inbound" else None,
                "category":      "cogs" if direction == "inbound" else "revenue",
                "raw_source":    "gib_efatura",
            })

        return invoices

    async def get_all_transactions(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """
        Hem gelen hem giden faturaları çekip CFO transaction formatında döndür.
        """
        try:
            inbox  = await self.get_inbox(start_date, end_date)
        except GIBError as exc:
            logger.warning("GİB inbox hatası: %s", exc)
            inbox = []

        try:
            outbox = await self.get_outbox(start_date, end_date)
        except GIBError as exc:
            logger.warning("GİB outbox hatası: %s", exc)
            outbox = []

        return inbox + outbox

    async def close(self) -> None:
        await self._http.aclose()


# ── Vergi Takvimi Hesaplama ────────────────────────────────────────────────────

def compute_tax_calendar(
    invoices: list[dict[str, Any]],
    period: str,           # YYYY-MM
    corporate_rate: float = 0.25,   # Kurumlar Vergisi oranı %25 (2024)
) -> dict[str, Any]:
    """
    e-Fatura verilerinden vergi takvimi oluştur.

    Hesaplanan vergiler:
      - KDV ödenecek: Giden fatura KDV - Gelen fatura KDV = Net KDV
      - Geçici Vergi: Dönem kârı × kurumlar vergisi oranı / 4
      - Stopaj (varsa): Hizmet faturalarında %10-20

    Returns:
        {
          "period": "2024-01",
          "kdv_collected": float,    (giden faturalardan)
          "kdv_paid": float,         (gelen faturalardan)
          "kdv_net": float,          (ödenecek/iade)
          "kdv_due_date": str,       (ertesi ayın 26'sı)
          "estimated_corporate_tax": float,
          "payment_calendar": [...]
        }
    """
    # KDV hesaplama
    outbound = [inv for inv in invoices if inv.get("direction") == "outbound"]
    inbound  = [inv for inv in invoices if inv.get("direction") == "inbound"]

    kdv_collected = sum(inv.get("vat_amount", 0) for inv in outbound)
    kdv_paid      = sum(inv.get("vat_amount", 0) for inv in inbound)
    kdv_net       = kdv_collected - kdv_paid

    # Net gelir hesaplama (kurumlar vergisi için)
    total_income  = sum(inv.get("net_amount", 0) for inv in outbound)
    total_expense = sum(inv.get("net_amount", 0) for inv in inbound)
    net_income    = total_income - total_expense
    geçici_vergi  = max(0, net_income * corporate_rate / 4)

    # Ödeme tarihleri
    try:
        year, month = int(period[:4]), int(period[5:7])
        next_month  = month + 1 if month < 12 else 1
        next_year   = year if month < 12 else year + 1
        kdv_due_date = f"{next_year:04d}-{next_month:02d}-26"

        geçici_months = {3: "05-17", 6: "08-17", 9: "11-17", 12: "02-17"}
        gecici_due = None
        for end_month, due in geçici_months.items():
            if month <= end_month:
                due_year = year if end_month >= month else year + 1
                gecici_due = f"{due_year:04d}-{due}"
                break
    except Exception:
        kdv_due_date = "N/A"
        gecici_due   = None

    payment_calendar = []

    if abs(kdv_net) > 0:
        payment_calendar.append({
            "type":        "KDV Beyannamesi",
            "amount":      round(kdv_net, 2),
            "due_date":    kdv_due_date,
            "direction":   "ödeme" if kdv_net > 0 else "iade",
            "description": f"{'Ödenecek' if kdv_net > 0 else 'İade edilecek'} KDV: {abs(kdv_net):,.2f} ₺",
        })

    if geçici_vergi > 0 and gecici_due:
        payment_calendar.append({
            "type":        "Geçici Vergi",
            "amount":      round(geçici_vergi, 2),
            "due_date":    gecici_due,
            "direction":   "ödeme",
            "description": f"Dönem kârı üzerinden %{corporate_rate*100:.0f} geçici vergi: {geçici_vergi:,.2f} ₺",
        })

    return {
        "period":                  period,
        "kdv_collected":           round(kdv_collected, 2),
        "kdv_paid":                round(kdv_paid, 2),
        "kdv_net":                 round(kdv_net, 2),
        "kdv_due_date":            kdv_due_date,
        "total_income":            round(total_income, 2),
        "total_expense":           round(total_expense, 2),
        "net_income":              round(net_income, 2),
        "estimated_corporate_tax": round(geçici_vergi, 2),
        "payment_calendar":        payment_calendar,
        "invoice_count": {
            "inbound":  len(inbound),
            "outbound": len(outbound),
        },
    }


def get_efatura_client(sandbox: bool = True) -> EFaturaClient | None:
    """
    Factory: create EFaturaClient from settings.
    Returns None if GİB credentials not configured.
    """
    try:
        from app.config import get_settings
        settings = get_settings()
        vkn      = getattr(settings, "gib_vkn", "")
        username = getattr(settings, "gib_username", "")
        password = getattr(settings, "gib_password", "")
        sandbox  = getattr(settings, "gib_sandbox", True)

        if not all([vkn, username, password]):
            logger.debug("GİB e-Fatura: kimlik bilgileri yapılandırılmamış")
            return None

        return EFaturaClient(vkn=vkn, username=username, password=password, sandbox=sandbox)
    except Exception as exc:
        logger.warning("GİB e-Fatura client oluşturulamadı: %s", exc)
        return None

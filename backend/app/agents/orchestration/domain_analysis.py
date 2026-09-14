"""Alan analizi — tek motor, gerçek veriyle; veri yoksa uydurma yok.

Each non-CFO domain used to have two engines. The orchestrator analysed files a
user uploaded. The kernel, when there were none, produced the same metrics from
the CFO figures and fixed sector constants — including values derived from
nothing at all: `security_score = health_score * 0.9 + 0.5`, an "open
vulnerabilities" count computed from that score, a lead time looked up from a
trend label. The CTO, COO and Risk pages showed only the kernel's numbers.

This module is the one entry point for every domain:

- **Real data present** (files attached to the job, or a connected source) →
  the domain's orchestrator runs on it, and the result says so.
- **Not enough** → no analysis. The answer says which data is missing, how a
  person without technical help gets it into the system, and shows only the
  figures the CFO books really contain for that domain — the technology or
  marketing spend in the bank movements, labelled with where it came from.

Nothing is estimated here. A page with no data says it has no data.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob
from app.models.data_source import DataSource, DataSourceType

logger = logging.getLogger(__name__)

ANALIZ_EDILDI = "analiz_edildi"
EKSIK_VERI = "eksik_veri"
VERI_YOK = "veri_yok"

# How a person gets each kind of file out of the tools they already use.
# Written for someone who does not know what a CSV is.
_NASIL: dict[str, str] = {
    DataSourceType.CLOUD_BILLING: "AWS: Faturalama → Cost Explorer → 'CSV indir'. Azure: Maliyet Yönetimi → Dışa aktar.",
    DataSourceType.GIT_LOG: "Entegrasyonlar sayfasından GitHub'ı bağlayın; ya da yazılım ekibinizden son 3 ayın 'git log' çıktısını isteyin.",
    DataSourceType.INCIDENT_LOG: "Jira, PagerDuty veya Opsgenie'de olay listesini Excel olarak dışa aktarın.",
    DataSourceType.SPRINT_DATA: "Jira: Raporlar → Velocity tablosu → Excel'e aktar.",
    DataSourceType.HEADCOUNT: "Bordro programınızdan (Logo, Mikro, Netsis) personel listesini Excel olarak alın.",
    DataSourceType.ATTRITION: "Son 12 ayda ayrılan çalışanların listesini İK'dan Excel olarak isteyin.",
    DataSourceType.COMPENSATION: "Bordro programınızdan maaş ve yan hak listesini Excel olarak alın.",
    DataSourceType.CAMPAIGN: "Google Ads / Meta Reklam Yöneticisi → Raporlar → 'İndir' (kampanya, harcama, dönüşüm).",
    DataSourceType.FUNNEL: "CRM'inizden (HubSpot, Salesforce) fırsat listesini Excel olarak dışa aktarın.",
    DataSourceType.COHORT: "Abonelik ya da e-ticaret panelinizden aylık müşteri tutma raporunu indirin.",
    DataSourceType.PROCESS: "Süreç sürelerini tuttuğunuz tabloyu (iş emri, sipariş işleme) Excel olarak yükleyin.",
    DataSourceType.RESOURCE: "Ekip kapasitesi ve doluluk tablonuzu Excel olarak yükleyin.",
    DataSourceType.SLA: "Destek sisteminizden (Zendesk, Freshdesk) SLA raporunu dışa aktarın.",
    DataSourceType.RISK_REGISTER: "Risk kayıt defterinizi (risk, olasılık, etki, sorumlu) Excel olarak yükleyin.",
    DataSourceType.LOSS_EVENTS: "Yaşanan kayıp olaylarının listesini (tarih, tutar, neden) Excel olarak yükleyin.",
    DataSourceType.KRI: "Takip ettiğiniz risk göstergelerini (gösterge, değer, eşik) Excel olarak yükleyin.",
    DataSourceType.FINDINGS: "İç denetim bulgu listesini Excel olarak yükleyin.",
    DataSourceType.CONTROLS: "Kontrol matrisinizi (kontrol, etkinlik, son test) Excel olarak yükleyin.",
    DataSourceType.COVERAGE: "Denetim planınızı (birim, son denetim, sıklık) Excel olarak yükleyin.",
    DataSourceType.POLICIES: "Şirket politikaları listesini (politika, durum, son gözden geçirme) yükleyin.",
    DataSourceType.VIOLATIONS: "Tespit edilen uyumsuzlukların listesini yükleyin.",
    DataSourceType.REGULATIONS: "Tabi olduğunuz mevzuat ve uyum durumunu (KVKK, SGK vb.) yükleyin.",
}

_ETIKET: dict[str, str] = {
    DataSourceType.CLOUD_BILLING: "Bulut faturası", DataSourceType.GIT_LOG: "Kod geçmişi (git log)",
    DataSourceType.INCIDENT_LOG: "Olay kayıtları", DataSourceType.SPRINT_DATA: "Sprint verisi",
    DataSourceType.HEADCOUNT: "Personel listesi", DataSourceType.ATTRITION: "Ayrılan çalışanlar",
    DataSourceType.COMPENSATION: "Ücret listesi", DataSourceType.CAMPAIGN: "Reklam kampanyaları",
    DataSourceType.FUNNEL: "Satış hunisi", DataSourceType.COHORT: "Müşteri tutma",
    DataSourceType.PROCESS: "Süreç süreleri", DataSourceType.RESOURCE: "Kaynak kullanımı",
    DataSourceType.SLA: "SLA raporu", DataSourceType.RISK_REGISTER: "Risk kayıt defteri",
    DataSourceType.LOSS_EVENTS: "Kayıp olayları", DataSourceType.KRI: "Risk göstergeleri",
    DataSourceType.FINDINGS: "Denetim bulguları", DataSourceType.CONTROLS: "Kontrol matrisi",
    DataSourceType.COVERAGE: "Denetim kapsamı", DataSourceType.POLICIES: "Politikalar",
    DataSourceType.VIOLATIONS: "Uyumsuzluklar", DataSourceType.REGULATIONS: "Mevzuat",
}


@dataclasses.dataclass(frozen=True)
class Alan:
    kod: str
    ad: str
    kaynaklar: tuple[str, ...]
    hepsi_gerekli: bool          # the orchestrator needs every file, not just one
    cfo_kategorileri: tuple[str, ...] = ()


ALANLAR: dict[str, Alan] = {
    "cto": Alan("cto", "Teknoloji (CTO)", (DataSourceType.CLOUD_BILLING, DataSourceType.GIT_LOG,
                DataSourceType.INCIDENT_LOG, DataSourceType.SPRINT_DATA), False, ("technology",)),
    "cmo": Alan("cmo", "Pazarlama (CMO)", (DataSourceType.CAMPAIGN, DataSourceType.FUNNEL,
                DataSourceType.COHORT), False, ("marketing",)),
    "coo": Alan("coo", "Operasyon (COO)", (DataSourceType.PROCESS, DataSourceType.RESOURCE,
                DataSourceType.SLA), False, ("rent", "utilities")),
    "chro": Alan("chro", "İnsan Kaynakları (CHRO)", (DataSourceType.HEADCOUNT, DataSourceType.ATTRITION,
                 DataSourceType.COMPENSATION), True, ("salary",)),
    "risk": Alan("risk", "Risk", (DataSourceType.RISK_REGISTER, DataSourceType.LOSS_EVENTS,
                 DataSourceType.KRI), True),
    "audit": Alan("audit", "İç Denetim", (DataSourceType.FINDINGS, DataSourceType.CONTROLS,
                  DataSourceType.COVERAGE), True),
    "compliance": Alan("compliance", "Uyum", (DataSourceType.POLICIES, DataSourceType.VIOLATIONS,
                       DataSourceType.REGULATIONS), False),
}

_KATEGORI_ETIKETI = {
    "technology": "teknoloji", "marketing": "pazarlama", "salary": "maaş",
    "rent": "kira", "utilities": "elektrik-su-internet",
}


class AlanBilinmiyor(LookupError):
    pass


def _read_as_csv(path: str, source_type: str = "") -> str | None:
    """File text for the orchestrators, in the columns and formats they read.

    A recognised table is rewritten to the parser's own column names with plain
    numbers and ISO dates (app/services/ingest): "Ad Soyad; Departman; Brüt
    Maaş" with "45.000,00" used to reach a parser that looks for `name` and
    `salary` and splits on commas, and every value fell back to a default. A
    file whose header cannot be found is passed as it is, as before.

    The CEO wizard read every attachment as UTF-8 text, so an .xlsx arrived as
    replacement characters — the most common thing a non-technical user uploads.
    """
    try:
        with open(path, "rb") as f:
            veri = f.read()
    except OSError as exc:
        logger.warning("Alan dosyası okunamadı %s: %s", path, exc)
        return None
    if source_type:
        from app.services.ingest.recognize import standart_csv, tabloyu_sec
        from app.services.ingest.table import OkunamayanDosya

        try:
            tablo = tabloyu_sec(veri, path, source_type)
        except OkunamayanDosya as exc:
            logger.warning("Alan dosyası okunamadı %s: %s", path, exc)
            return None
        if tablo is not None:
            return standart_csv(tablo, source_type)[0]
    try:
        if path.lower().endswith((".xlsx", ".xls")):
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(veri), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            out = io.StringIO()
            w = csv.writer(out)
            for row in ws.iter_rows(values_only=True):
                if any(v not in (None, "") for v in row):
                    w.writerow(["" if v is None else v for v in row])
            wb.close()
            return out.getvalue()
        return veri.decode("utf-8-sig", errors="replace")
    except Exception as exc:
        logger.warning("Alan dosyası okunamadı %s: %s", path, exc)
        return None


def _json_safe(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _json_safe(dataclasses.asdict(obj))
    if hasattr(obj, "model_dump"):
        return _json_safe(obj.model_dump())
    if isinstance(obj, dict):
        # The inputs are the user's own files; echoing them back adds nothing.
        return {str(k): _json_safe(v) for k, v in obj.items()
                if not (str(k).endswith("_csv") or k in ("git_log_text", "settings"))}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


async def _cfo_gercek(db: AsyncSession, job_id: str, alan: Alan) -> dict[str, Any]:
    """Only what the CFO report really contains for this domain."""
    from app.models.report import Report, ReportFormat

    rep = (
        await db.execute(
            select(Report)
            .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
            .order_by(desc(Report.created_at))
        )
    ).scalars().first()
    data = (rep.data if rep else None) or {}
    pnl = data.get("pnl") or {}
    opex = pnl.get("opex") or {}
    revenue = int(pnl.get("revenue") or 0)
    kalemler = []
    for kat in alan.cfo_kategorileri:
        if kat in opex:
            tutar = int(opex.get(kat) or 0)
            kalemler.append({
                "kategori": kat,
                "etiket": f"Banka hareketlerindeki {_KATEGORI_ETIKETI.get(kat, kat)} harcaması",
                "tutar_kurus": tutar,
                "gelire_orani": round(tutar / revenue, 4) if revenue else None,
                "kaynak": f"CFO raporu — '{kat}' kategorisindeki işlemlerin toplamı",
            })
    if alan.kod == "risk":
        forecast = data.get("forecast") or {}
        base = ((forecast.get("scenarios") or {}).get("base") or {})
        if base.get("runway_months") is not None:
            kalemler.append({
                "kategori": "runway", "etiket": "Nakit ömrü (baz senaryo)",
                "deger": base.get("runway_months"), "birim": "ay",
                "kaynak": "CFO tahmini — bu işin nakit akışından",
            })
        alerts = ((data.get("cashflow") or {}).get("alerts") or [])
        if alerts:
            kalemler.append({
                "kategori": "nakit_uyarilari", "etiket": "Nakit akışı uyarıları",
                "deger": len(alerts), "birim": "adet", "kaynak": "CFO nakit akışı analizi",
            })
    return {"var": bool(rep), "kalemler": kalemler}


async def _sources(db: AsyncSession, job_id: str, alan: Alan) -> dict[str, DataSource]:
    rows = (
        await db.execute(
            select(DataSource)
            .where(DataSource.job_id == job_id, DataSource.domain == alan.kod)
            .order_by(desc(DataSource.created_at))
        )
    ).scalars().all()
    latest: dict[str, DataSource] = {}
    for r in rows:
        latest.setdefault(str(r.source_type), r)
    return latest


async def durum(db: AsyncSession, job: AnalysisJob, alan_kodu: str) -> dict[str, Any]:
    """What this domain has, lacks, and what the CFO books already say — no run."""
    alan = ALANLAR.get(alan_kodu)
    if alan is None:
        raise AlanBilinmiyor(alan_kodu)
    mevcut = await _sources(db, job.id, alan)
    kaynaklar = [
        {"tip": str(t), "etiket": _ETIKET[t], "yuklendi": str(t) in mevcut, "nasil": _NASIL[t],
         "dosya": mevcut[str(t)].filename if str(t) in mevcut else None}
        for t in alan.kaynaklar
    ]
    eksik = [k["tip"] for k in kaynaklar if not k["yuklendi"]]
    yeterli = not eksik if alan.hepsi_gerekli else len(eksik) < len(kaynaklar)
    if yeterli:
        d = ANALIZ_EDILDI
    elif len(eksik) < len(kaynaklar):
        d = EKSIK_VERI
    else:
        d = VERI_YOK
    sinyaller = None
    if alan.kod == "cto" and job.org_id:
        from app.services.eng_signals import summarize_eng_signals

        try:
            sinyaller = await summarize_eng_signals(str(job.org_id), db)
        except Exception as exc:
            logger.debug("GitHub sinyalleri okunamadı: %s", exc)
    return {
        "alan": alan.kod,
        "ad": alan.ad,
        "durum": d if d != ANALIZ_EDILDI else "hazir",
        "hepsi_gerekli": alan.hepsi_gerekli,
        "kaynaklar": kaynaklar,
        "eksik": eksik,
        "cfo_gercek": await _cfo_gercek(db, job.id, alan),
        "bagli_kaynak_sinyalleri": _json_safe(sinyaller) if sinyaller else None,
    }


async def analiz_et(db: AsyncSession, job: AnalysisJob, alan_kodu: str) -> dict[str, Any]:
    """Run the domain's orchestrator on the job's real files, or say why not."""
    out = await durum(db, job, alan_kodu)
    if out["durum"] != "hazir":
        out["sonuc"] = None
        out["neden"] = (
            "Bu alan için gerekli dosyaların hepsi yok." if out["hepsi_gerekli"] and out["durum"] == EKSIK_VERI
            else "Bu alan için yüklenmiş veri yok."
        )
        return out

    alan = ALANLAR[alan_kodu]
    mevcut = await _sources(db, job.id, alan)
    kwargs: dict[str, Any] = {}
    okunamayan = []
    for src in mevcut.values():
        text = _read_as_csv(src.file_path, str(src.source_type))
        kw = src.pipeline_kwarg()
        if text is None or not kw:
            okunamayan.append(src.filename)
            continue
        kwargs[kw] = text
    if okunamayan:
        out.update(durum=EKSIK_VERI, sonuc=None, neden=f"Okunamayan dosya: {', '.join(okunamayan)}")
        return out

    org_id = str(job.org_id) if job.org_id else None
    result: Any
    if alan_kodu == "cto":
        from app.agents.cto.orchestrator import run_cto_pipeline
        result = await run_cto_pipeline(job_id=job.id, org_id=org_id, **kwargs)
    elif alan_kodu == "cmo":
        from app.agents.cmo.orchestrator import run_cmo_pipeline
        result = await run_cmo_pipeline(job_id=job.id, org_id=org_id, **kwargs)
    elif alan_kodu == "coo":
        from app.agents.coo.orchestrator import run_coo_pipeline
        result = await run_coo_pipeline(job_id=job.id, org_id=org_id, **kwargs)
    elif alan_kodu == "chro":
        from app.agents.chro.orchestrator import run_chro_pipeline
        result = await run_chro_pipeline(org_id=org_id, **kwargs)
    elif alan_kodu == "risk":
        from app.agents.risk.orchestrator import run_risk_pipeline
        result = await run_risk_pipeline(**kwargs)
    elif alan_kodu == "audit":
        from app.agents.audit.orchestrator import run_audit_pipeline
        result = await run_audit_pipeline(org_id=org_id, **kwargs)
    else:
        from app.agents.compliance.orchestrator import run_compliance_pipeline
        result = await run_compliance_pipeline(job_id=job.id, org_id=org_id, **kwargs)

    out["durum"] = ANALIZ_EDILDI
    out["sonuc"] = _json_safe(dict(result))
    out["provenance"] = {"data_source": "real", "synthetic": False,
                         "basis": "yüklenen dosyalar: " + ", ".join(s.filename for s in mevcut.values())}
    return out

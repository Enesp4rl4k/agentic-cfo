"""
KVKK / GDPR uyumluluk uçları (SEC-3) — eski yollar, artık kayıt defterinden beslenir.

  GET /compliance/data-inventory   → Kişisel veri haritası (kayıt defteri: tablolar, depolar, üçüncü taraflar)
  GET /compliance/data-export      → Kişinin kendi kişisel verisi (KVKK Md. 11/b)  [= GET /privacy/my-data]
  GET /compliance/retention-report → Saklama politikası: gerçekten uygulanan değerler

Silme: `org_erasure.py` (şirketin tamamı), `member_erasure.py` (bir kişi). Şirket dışa aktarımı, saklama ayarı, bildirim
sürümleri ve ekran: `privacy_data.py`. Eski sürüm sabit sayılarla "politika" yazıyordu (işlemler 2 yıl, denetim 5 yıl),
"VERBİS'e kayıtlıdır" diyordu ve hiçbirini uygulamıyordu; bunlar kaldırıldı (docs/kvkk/veri-envanteri-farklar.md).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.privacy_data import my_data
from app.config import get_settings
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.services.privacy import retention
from app.services.privacy.registry import THIRD_PARTIES
from app.services.privacy.registry_stores import STORES
from app.services.privacy.registry_tables import TABLES

router = APIRouter()


@router.get("/compliance/data-inventory")
async def data_inventory(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """KVKK Md. 10 / GDPR Art. 13-14: hangi kişisel veri, kimin, hangi amaçla, nereye gidiyor (ürünün haritası)."""
    return {
        "data": {
            "generated_at": datetime.now(UTC).isoformat(),
            "tables": [{"table": n, "purpose": t.purpose, "subject": t.subject.value, "retention_class": t.retention.value,
                        "personal_fields": sorted(t.columns), "third_parties": [f.value for f in t.flows]}
                       for n, t in sorted(TABLES.items())],
            "stores": [{"store": s.key, "holds": s.holds, "retention_class": s.retention.value, "lifetime": s.ttl} for s in STORES],
            "third_parties": [{"key": k.value, "name": v.name, "sends": v.sends, "masked": v.masked} for k, v in THIRD_PARTIES.items()],
            "subject_rights": [
                "Kişisel verilerinize erişim (Md. 11/a): GET /privacy/my-data",
                "Silinmesini isteme (Md. 11/e): POST /privacy/member-erasure; şirket için /compliance/org-erasure",
                "Aktarıldığı üçüncü kişileri öğrenme (Md. 11/f): GET /privacy/overview",
            ],
        },
        "error": None,
    }


@router.get("/compliance/data-export")
async def export_personal_data(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    """KVKK Md. 11/b / GDPR Art. 20: kişinin kendi verisi (GET /privacy/my-data ile aynı)."""
    return await my_data(current_user=current_user, db=db)


@router.get("/compliance/retention-report")
async def retention_report(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Saklama: platform değerleri, bu şirketin etkin değerleri ve işin gerçekten silip silmediği."""
    org = await db.get(Organization, str(current_user.org_id)) if current_user.org_id else None
    return {
        "data": {
            "platform": retention.platform_policy(), "effective_for_this_company": retention.effective_policy(org),
            "automatic_deletion": not get_settings().retention_dry_run,
            "never_purged": "defter kayıtları (işlemler, defter, yevmiye, açık kalemler, onaylar, kararlar): hukuki süre açık soru (docs/kvkk/avukata-sorular.md Q2)",
            "unit": "days; 0 = keep",
        },
        "error": None,
    }

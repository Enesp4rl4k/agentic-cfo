"""What each kind of file looks like: its columns, in Turkish and English.

One schema per data source type. Each field's `ad` is the column name the
domain's own parser looks for first (its `_col(...)` candidates, checked by
tests/test_ingest_schemas.py), so a normalised file is read without guessing.
`esler` are the headers people actually write; they are matched after
folding (case, Turkish letters, punctuation, units in brackets).

`zorunlu` fields decide recognition: a file is a candidate for a type only if
it has every one of them. Keep them distinctive — a column every table has
("tarih", "tutar") cannot tell a bank statement from a loss register on its own.
"""
from __future__ import annotations

from dataclasses import dataclass

# Field kinds: how a value is normalised.
METIN = "metin"        # kept as written
SAYI = "sayi"          # "45.000,00" / "45,000.00" / "%12" → 45000.00 / 12
TARIH = "tarih"        # "05.01.2024", Excel dates → 2024-01-05
KATEGORI = "kategori"  # Turkish status/severity words → the English the parsers compare
EVET_HAYIR = "evet_hayir"

BANKA_EKSTRESI = "bank_statement"


@dataclass(frozen=True)
class Alan:
    ad: str
    tur: str
    zorunlu: bool
    esler: tuple[str, ...]
    # Headers whose values are monthly where the parser reads a year. In Turkey
    # "Brüt Maaş" is a monthly figure; the HR parsers sum `salary` as annual
    # pay, so a Turkish payroll read as it stands came out twelve times small.
    aylik: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sema:
    tur: str            # DataSourceType value, or "bank_statement"
    alan: str           # domain: cfo | cto | chro | cmo | coo | risk | audit | compliance
    etiket: str         # what the person is told the file is
    alanlar: tuple[Alan, ...]
    # At least one of these must be present too — a statement has an amount
    # column or debit/credit columns, and either is enough.
    en_az_biri: tuple[str, ...] = ()


def A(ad: str, tur: str, *esler: str, zorunlu: bool = False, aylik: tuple[str, ...] = ()) -> Alan:  # shorthand
    return Alan(ad, tur, zorunlu, (ad, *esler, *aylik), aylik)


SEMALAR: tuple[Sema, ...] = (
    Sema(BANKA_EKSTRESI, "cfo", "Banka ekstresi / hesap hareketleri", (
        A("tarih", TARIH, "date", "transaction date", "işlem tarihi", "islem tarihi", "valör", "valör tarihi",
          "tarih saat", "işlem tarih", zorunlu=True),
        A("açıklama", METIN, "description", "işlem açıklaması", "açıklama detayı", "detay", "işlem detayı",
          "işlem", "karşı taraf", "aciklama", zorunlu=True),
        A("tutar", SAYI, "amount", "işlem tutarı", "tutar tl", "hareket tutarı", zorunlu=False),
        A("borç", SAYI, "borç tutarı", "çıkan", "giden", "debit"),
        A("alacak", SAYI, "alacak tutarı", "giren", "gelen", "credit"),
        A("bakiye", SAYI, "balance", "kalan bakiye", "hesap bakiyesi"),
        A("tip", KATEGORI, "type", "işlem tipi", "işlem türü"),
        A("kategori", METIN, "category"),
    ), en_az_biri=("tutar", "borç", "alacak")),

    # ── CTO ────────────────────────────────────────────────────────────────
    Sema("cloud_billing", "cto", "Bulut / sunucu faturası", (
        A("service", METIN, "product_name", "productname", "service_name", "servis", "hizmet", "hizmet adı",
          "ürün", "ürün adı", "servis adı", zorunlu=True),
        A("cost", SAYI, "amount", "unblended_cost", "totalcost", "maliyet", "tutar", "ücret", "toplam maliyet",
          zorunlu=True),
        A("date", TARIH, "usage_start_date", "month", "start_date", "tarih", "dönem", "ay", "kullanım tarihi"),
        A("description", METIN, "usage_type", "resource_id", "açıklama", "kullanım türü", "kaynak"),
    )),
    Sema("incident_log", "cto", "Olay / arıza kayıtları", (
        A("id", METIN, "incident_id", "number", "olay no", "kayıt no", "numara"),
        A("title", METIN, "name", "description", "summary", "başlık", "olay", "özet", "arıza", zorunlu=True),
        A("severity", KATEGORI, "priority", "urgency", "level", "önem", "önem derecesi", "öncelik", "aciliyet",
          zorunlu=True),
        A("service", METIN, "affected_service", "component", "team", "servis", "etkilenen servis", "bileşen"),
        A("started_at", TARIH, "created_at", "opened_at", "start_time", "timestamp", "başlangıç",
          "başlangıç zamanı", "açılış zamanı", "oluşturulma", zorunlu=True),
        A("resolved_at", TARIH, "closed_at", "end_time", "resolved", "çözüm zamanı", "çözülme", "kapanış zamanı",
          "bitiş"),
        A("detected_at", TARIH, "acknowledged_at", "first_ack", "tespit zamanı", "fark edilme"),
    )),
    Sema("sprint_data", "cto", "Sprint / iterasyon verisi", (
        A("sprint_name", METIN, "sprint", "name", "iteration", "sprint adı", "iterasyon", zorunlu=True),
        A("planned_points", SAYI, "planned", "story_points_planned", "capacity", "commitment", "planlanan",
          "planlanan puan", "taahhüt", zorunlu=True),
        A("completed_points", SAYI, "completed", "story_points_completed", "velocity", "done", "tamamlanan",
          "tamamlanan puan", zorunlu=True),
        A("start_date", TARIH, "date", "sprint_start", "period", "başlangıç tarihi", "başlangıç"),
        A("carry_over", SAYI, "carryover", "carried_over", "rolled_over", "devreden", "devreden puan"),
    )),

    # ── CHRO ───────────────────────────────────────────────────────────────
    Sema("headcount", "chro", "Personel listesi", (
        A("name", METIN, "employee", "employee_name", "ad soyad", "adı soyadı", "ad", "isim", "personel",
          "çalışan", "personel adı", "çalışan adı", zorunlu=True),
        A("level", KATEGORI, "seniority", "grade", "rank", "kademe", "seviye", "kıdem seviyesi", "unvan seviyesi"),
        A("department", METIN, "dept", "team", "function", "departman", "bölüm", "birim", "ekip", zorunlu=True),
        A("role", METIN, "title", "job_title", "position", "unvan", "görev", "pozisyon", "görevi"),
        A("salary", SAYI, "base_salary", "compensation", "base", "yıllık maaş", "yıllık brüt maaş", "yıllık ücret",
          aylik=("maaş", "brüt maaş", "aylık maaş", "aylık brüt maaş", "ücret", "brüt ücret")),
        A("location", METIN, "office", "city", "region", "lokasyon", "şehir", "ofis", "şube"),
        A("start_date", TARIH, "hire_date", "joined", "işe giriş tarihi", "işe başlama tarihi", "giriş tarihi",
          "işe giriş"),
        A("status", KATEGORI, "employment_status", "state", "durum", "çalışma durumu"),
    )),
    Sema("attrition", "chro", "İşten ayrılanlar", (
        A("name", METIN, "employee", "employee_name", "ad soyad", "adı soyadı", "isim", "personel", "çalışan",
          zorunlu=True),
        A("level", KATEGORI, "seniority", "grade", "kademe", "seviye"),
        A("department", METIN, "dept", "team", "departman", "bölüm", "birim"),
        A("departure_date", TARIH, "exit_date", "last_day", "ayrılış tarihi", "çıkış tarihi", "işten çıkış tarihi",
          "işten ayrılış tarihi", "son çalışma günü", zorunlu=True),
        A("tenure", SAYI, "tenure_months", "months", "years_employed", "kıdem", "kıdem ay", "çalışma süresi"),
        A("reason", METIN, "departure_reason", "attrition_reason", "cause", "ayrılış nedeni", "çıkış nedeni",
          "neden", "ayrılma nedeni"),
        A("replaced", EVET_HAYIR, "replacement_hired", "backfilled", "yerine alındı", "yerine alım"),
    )),
    Sema("compensation", "chro", "Ücret ve yan haklar", (
        A("name", METIN, "employee", "employee_name", "ad soyad", "adı soyadı", "isim", "personel", "çalışan",
          zorunlu=True),
        A("level", KATEGORI, "seniority", "grade", "kademe", "seviye"),
        A("department", METIN, "dept", "team", "departman", "bölüm", "birim"),
        A("salary", SAYI, "base_salary", "base", "yıllık maaş", "yıllık brüt maaş", "yıllık ücret", zorunlu=True,
          aylik=("maaş", "brüt maaş", "aylık maaş", "aylık brüt maaş", "ücret", "brüt ücret")),
        A("bonus", SAYI, "bonus_percentage", "target_bonus", "prim", "ikramiye", "bonus oranı", zorunlu=True),
        A("equity_shares", SAYI, "equity", "stock_options", "option_grant", "options", "hisse", "hisse opsiyonu"),
        A("vesting", METIN, "vest_date", "vesting_schedule", "hak ediş"),
        A("benefits", SAYI, "benefits_cost", "benefits_package", "yan haklar", "yan hak tutarı"),
        A("market_salary", SAYI, "market_rate", "industry_rate", "yıllık piyasa maaşı",
          aylik=("piyasa maaşı", "piyasa ücreti")),
    )),

    # ── CMO ────────────────────────────────────────────────────────────────
    Sema("campaign", "cmo", "Reklam kampanyaları", (
        A("campaign", METIN, "campaign_name", "name", "ad_name", "kampanya", "kampanya adı", "reklam adı",
          zorunlu=True),
        A("channel", METIN, "source", "network", "platform", "objective", "kanal", "kaynak", "hedef"),
        A("spend", SAYI, "cost", "amount_spent", "budget_spent", "total_cost", "harcama", "harcanan tutar",
          "maliyet", "harcanan", zorunlu=True),
        A("revenue", SAYI, "value", "conversion_value", "total_value", "sales", "gelir", "dönüşüm değeri",
          "satış tutarı"),
        A("conversions", SAYI, "leads", "results", "purchases", "acquisitions", "dönüşüm", "dönüşümler",
          "sonuçlar", "satın alma"),
        A("clicks", SAYI, "link_clicks", "total_clicks", "tıklama", "tıklamalar", "bağlantı tıklamaları"),
        A("impressions", SAYI, "reach", "total_impressions", "gösterim", "gösterimler", "erişim"),
    )),
    Sema("funnel", "cmo", "Satış hunisi / potansiyel müşteriler", (
        A("id", METIN, "lead_id", "contact_id", "record_id", "kayıt no", "müşteri no"),
        A("stage", KATEGORI, "status", "lifecycle_stage", "lead_status", "aşama", "huni aşaması", "fırsat aşaması",
          zorunlu=True),
        A("source", METIN, "lead_source", "channel", "utm_source", "origin", "kaynak", "kanal"),
        A("created", TARIH, "created_date", "date", "created_at", "lead_date", "oluşturma tarihi", "kayıt tarihi",
          zorunlu=True),
        A("closed", TARIH, "closed_date", "close_date", "converted_date", "won_date", "kapanış tarihi",
          "kazanma tarihi"),
    )),
    Sema("cohort", "cmo", "Müşteri tutma (kohort)", (
        A("cohort", METIN, "period", "cohort_date", "month", "week", "date", "kohort", "dönem", zorunlu=True),
        A("users", SAYI, "size", "cohort_size", "new_users", "customers", "kullanıcı", "yeni müşteri",
          "müşteri sayısı", zorunlu=True),
        A("retention_30d", SAYI, "month_1", "retention_month_1", "day_30", "30d_retention", "m1_retention",
          "ret_30", "30 gün tutma", "1 ay tutma"),
        A("retention_90d", SAYI, "month_3", "retention_month_3", "day_90", "90d_retention", "m3_retention",
          "ret_90", "90 gün tutma", "3 ay tutma"),
        A("ltv", SAYI, "lifetime_value", "revenue", "avg_ltv", "arpu", "value", "yaşam boyu değer"),
        A("cac", SAYI, "acquisition_cost", "customer_acquisition_cost", "cost", "müşteri edinme maliyeti",
          "edinme maliyeti"),
    )),

    # ── COO ────────────────────────────────────────────────────────────────
    Sema("sla", "coo", "Destek talepleri / SLA", (
        A("id", METIN, "ticket_id", "issue_id", "case_id", "record_id", "talep no", "bilet no", "kayıt no",
          zorunlu=True),
        A("tier", KATEGORI, "priority", "severity", "sla_tier", "level", "öncelik", "önem"),
        A("created", TARIH, "created_at", "created_date", "open_date", "date", "oluşturma tarihi",
          "açılış tarihi", "talep tarihi", zorunlu=True),
        A("resolved", TARIH, "closed_at", "resolved_at", "close_date", "resolution_date", "closed",
          "çözüm tarihi", "kapanış tarihi"),
        A("response_time_hours", SAYI, "response_hrs", "first_response", "response_time",
          "time_to_first_response", "ilk yanıt süresi", "yanıt süresi saat"),
        A("resolution_time_hours", SAYI, "resolution_hrs", "resolution_time", "time_to_resolve", "ttfr",
          "çözüm süresi", "çözüm süresi saat"),
        A("nps", SAYI, "nps_score", "satisfaction", "csat", "rating", "memnuniyet", "puan"),
        A("category", METIN, "issue_type", "type", "topic", "subject_area", "kategori", "konu", "talep türü"),
        A("status", KATEGORI, "state", "ticket_status", "durum"),
    )),
    Sema("process", "coo", "Süreç süreleri", (
        A("process", METIN, "name", "process_name", "workflow", "task", "süreç", "süreç adı", "iş akışı",
          zorunlu=True),
        A("cycle_time", SAYI, "duration_days", "avg_cycle_days", "lead_time_days", "cycle_time_days",
          "çevrim süresi", "süre gün", "ortalama süre", "işlem süresi", zorunlu=True),
        A("throughput", SAYI, "weekly_output", "output_per_week", "completed_per_week", "velocity",
          "haftalık çıktı", "tamamlanan"),
        A("wip", SAYI, "in_progress", "active_items", "work_in_progress", "backlog", "devam eden", "bekleyen"),
        A("team", METIN, "department", "owner", "squad", "ekip", "departman", "sorumlu"),
        A("capacity", SAYI, "max_throughput", "max_output", "theoretical_throughput", "kapasite"),
        A("error_rate", SAYI, "rework_rate", "defect_rate", "failure_rate", "error_pct", "hata oranı",
          "yeniden işleme oranı"),
        A("dependencies", SAYI, "upstream_deps", "blockers", "dependency_count", "depends_on", "bağımlılık"),
    )),
    Sema("resource", "coo", "Ekip kapasitesi", (
        A("team", METIN, "department", "dept", "squad", "group", "name", "ekip", "departman", "birim",
          zorunlu=True),
        A("headcount", SAYI, "ftes", "fte", "employees", "count", "staff", "kişi sayısı", "çalışan sayısı",
          "personel sayısı", zorunlu=True),
        A("utilization", SAYI, "utilization_rate", "util_pct", "capacity_used", "billable_rate", "doluluk",
          "kullanım oranı", "doluluk oranı"),
        A("output", SAYI, "tasks_completed", "deliverables", "weekly_output", "monthly_output", "productivity",
          "çıktı", "tamamlanan iş"),
        A("capacity", SAYI, "max_capacity", "max_output", "target_output", "kapasite"),
        A("cost", SAYI, "labor_cost", "monthly_cost", "salary_total", "maliyet", "aylık maliyet",
          "işçilik maliyeti"),
    )),

    # ── Risk ───────────────────────────────────────────────────────────────
    Sema("risk_register", "risk", "Risk kayıt defteri", (
        A("risk_id", METIN, "id", "ref", "risk no"),
        A("risk", METIN, "title", "description", "risk_title", "risk adı", "risk tanımı", zorunlu=True),
        A("category", METIN, "type", "domain", "kategori", "tür"),
        A("likelihood", SAYI, "probability", "prob", "olasılık", zorunlu=True),
        A("impact", SAYI, "severity", "consequence", "etki", zorunlu=True),
        A("owner", METIN, "risk_owner", "responsible", "sorumlu", "risk sahibi"),
        A("status", KATEGORI, "state", "risk_status", "durum"),
        A("mitigation", METIN, "control", "treatment", "action", "önlem", "aksiyon", "kontrol"),
    )),
    Sema("loss_events", "risk", "Kayıp olayları", (
        A("date", TARIH, "event_date", "loss_date", "occurred", "tarih", "olay tarihi", zorunlu=True),
        A("category", METIN, "type", "risk_category", "kategori", "tür"),
        A("description", METIN, "event", "incident", "details", "açıklama", "olay"),
        A("gross_loss", SAYI, "loss", "gross_amount", "kayıp", "kayıp tutarı", "brüt kayıp", zorunlu=True),
        A("recovery", SAYI, "recovered", "recovery_amount", "geri kazanım", "tahsil edilen"),
        A("root_cause", METIN, "cause", "root_cause_category", "kök neden", "neden"),
        A("status", KATEGORI, "resolution_status", "durum"),
    )),
    Sema("kri", "risk", "Risk göstergeleri (KRI)", (
        A("kri", METIN, "kri_name", "indicator", "name", "gösterge", "gösterge adı", zorunlu=True),
        A("category", METIN, "type", "domain", "kategori"),
        A("current_value", SAYI, "value", "current", "actual", "değer", "güncel değer", "mevcut değer",
          zorunlu=True),
        A("threshold_red", SAYI, "red_threshold", "red_limit", "limit_red", "kırmızı eşik", "kırmızı limit",
          zorunlu=True),
        A("threshold_amber", SAYI, "amber_threshold", "amber_limit", "limit_amber", "sarı eşik", "sarı limit",
          "turuncu eşik"),
        A("unit", METIN, "measure", "units", "birim"),
        A("trend", METIN, "direction", "movement", "eğilim"),
        A("owner", METIN, "kri_owner", "responsible", "sorumlu"),
    )),

    # ── Audit ──────────────────────────────────────────────────────────────
    Sema("findings", "audit", "Denetim bulguları", (
        A("finding_id", METIN, "id", "ref", "bulgu no"),
        A("title", METIN, "finding", "description", "bulgu", "başlık", zorunlu=True),
        A("severity", KATEGORI, "rating", "level", "önem", "önem derecesi", "risk derecesi", zorunlu=True),
        A("status", KATEGORI, "remediation_status", "state", "durum", "aksiyon durumu"),
        A("due_date", TARIH, "remediation_due", "target_date", "hedef tarih", "termin", "son tarih"),
        A("owner", METIN, "responsible", "finding_owner", "sorumlu"),
        A("category", METIN, "type", "area", "kategori", "alan"),
        A("repeat", EVET_HAYIR, "repeat_finding", "is_repeat", "tekrar", "tekrarlayan"),
    )),
    Sema("controls", "audit", "Kontrol matrisi", (
        A("control_id", METIN, "id", "ref", "kontrol no"),
        A("name", METIN, "control", "control_name", "kontrol", "kontrol adı", zorunlu=True),
        A("category", METIN, "type", "domain", "kategori"),
        A("design_effectiveness", KATEGORI, "design", "design_score", "tasarım etkinliği", zorunlu=True),
        A("operating_effectiveness", KATEGORI, "operating", "operating_score", "işleyiş etkinliği",
          "operasyonel etkinlik"),
        A("last_tested", TARIH, "last_test_date", "tested_date", "son test tarihi", "son test"),
        A("owner", METIN, "control_owner", "sorumlu", "kontrol sahibi"),
    )),
    Sema("coverage", "audit", "Denetim planı / kapsamı", (
        A("unit", METIN, "name", "auditable_unit", "entity", "birim", "denetlenen birim", zorunlu=True),
        A("category", METIN, "type", "domain", "kategori"),
        A("last_audit", TARIH, "last_audited", "last_review", "son denetim", "son denetim tarihi", zorunlu=True),
        A("frequency", METIN, "audit_frequency", "cycle", "sıklık", "denetim sıklığı"),
        A("risk_rating", KATEGORI, "risk", "risk_level", "risk derecesi", "risk seviyesi"),
        A("scheduled_next", TARIH, "next_audit", "next_scheduled", "sonraki denetim", "planlanan denetim"),
    )),

    # ── Compliance ─────────────────────────────────────────────────────────
    Sema("policies", "compliance", "Şirket politikaları", (
        A("policy", METIN, "policy_name", "name", "politika", "politika adı", "prosedür", zorunlu=True),
        A("severity", KATEGORI, "level", "criticality", "önem", "kritiklik"),
        A("status", KATEGORI, "state", "durum", zorunlu=True),
        A("last_review", TARIH, "last_reviewed", "review_date", "son gözden geçirme", "son revizyon",
          "revizyon tarihi"),
        A("owner", METIN, "responsible", "owner_name", "sorumlu"),
        A("category", METIN, "type", "domain", "kategori"),
    )),
    Sema("violations", "compliance", "Uyumsuzluklar", (
        A("violation", METIN, "title", "name", "description", "finding", "uyumsuzluk", "ihlal", zorunlu=True),
        A("policy_id", METIN, "policy", "policy_ref", "control", "politika", "ilgili politika"),
        A("severity", KATEGORI, "level", "priority", "criticality", "önem", "öncelik"),
        A("date_found", TARIH, "found_date", "created_at", "discovered_at", "date", "tespit tarihi", "tarih",
          zorunlu=True),
        A("due_date", TARIH, "remediation_due", "target_date", "deadline", "hedef tarih", "termin"),
        A("remediation_status", KATEGORI, "status", "state", "durum", "düzeltme durumu"),
        A("responsible_party", METIN, "owner", "assignee", "responsible", "sorumlu"),
        A("framework", METIN, "regulation", "standard", "source", "mevzuat", "standart"),
    )),
    Sema("regulations", "compliance", "Mevzuat ve uyum durumu", (
        A("regulation", METIN, "framework", "standard", "source", "mevzuat", "düzenleme", "standart",
          zorunlu=True),
        A("requirement", METIN, "control", "control_id", "requirement_id", "item", "gereklilik", "madde",
          "yükümlülük", zorunlu=True),
        A("compliance_status", KATEGORI, "status", "compliance", "state", "uyum durumu", "durum", zorunlu=True),
        A("last_audit", TARIH, "last_audit_date", "audited_at", "audit_date", "son denetim"),
        A("next_audit", TARIH, "next_audit_date", "review_date", "sonraki denetim"),
        A("control_owner", METIN, "owner", "responsible", "assignee", "sorumlu"),
        A("evidence_status", KATEGORI, "evidence", "documentation", "kanıt durumu", "belge durumu"),
        A("risk_level", KATEGORI, "risk", "severity", "impact", "risk seviyesi"),
    )),
)

SEMA_BY_TUR: dict[str, Sema] = {s.tur: s for s in SEMALAR}

# Turkish category words → the English the parsers compare against. Values not
# listed are kept as written, lower-cased.
KATEGORI_DEGERLERI: dict[str, str] = {
    "kritik": "critical", "çok yüksek": "critical", "yüksek": "high", "orta": "medium", "düşük": "low",
    "açık": "open", "kapalı": "closed", "çözüldü": "resolved", "çözümlendi": "resolved",
    "tamamlandı": "completed", "devam ediyor": "in_progress", "beklemede": "pending",
    "aktif": "active", "pasif": "inactive", "ayrıldı": "terminated",
    "uyumlu": "compliant", "uyumsuz": "non_compliant", "kısmi": "partial", "kısmen uyumlu": "partial",
    "etkin": "effective", "etkili": "effective", "etkisiz": "ineffective", "etkin değil": "ineffective",
    "kısmen etkin": "partially_effective",
}
# Job levels are not translated: "uzman" or "kıdemli" means something different
# in every company, and a guessed mapping would be a guessed analysis.

EVET = frozenset({"evet", "var", "e", "yes", "y", "true", "1", "x"})
HAYIR = frozenset({"hayır", "hayir", "yok", "h", "no", "n", "false", "0"})

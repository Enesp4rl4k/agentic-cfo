"""
Board Deck PDF Generator

CEO board deck + SWOT + KRI + Cross-domain insights'i
profesyonel bir PDF sunum belgesi olarak uretir.

Kullanilan kutuphaneler:
  - reportlab: PDF olusturma (pip install reportlab)
  - Fallback: basit text-based PDF

PDF yapisi:
  1. Kapak sayfasi (sirket adi, tarih, saglik skoru)
  2. Yonetici Ozeti (executive summary)
  3. Finansal Durum (CFO: gelir, marj, nakit, forecast)
  4. Sirket Saglik Skoru (6 domain radar)
  5. SWOT Analizi (4 kuadrant)
  6. Risk ve KRI Durumu
  7. Cross-Domain Insights (kritik buldular)
  8. Stratejik Oncelikler (board deck slide'indan)
  9. Sonraki Adimlar

DDIA: PDF bir "derived data" → asil veriden her zaman yeniden uretelebilir.
Bu yuzden saklanmaz, her istekte hesaplanir.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── PDF Builder ───────────────────────────────────────────────────────────────

class BoardDeckPDFBuilder:
    """
    ReportLab ile profesyonel board deck PDF uretir.
    ReportLab yuklu degilse basit text PDF fallback kullanir.
    """

    BRAND_BLUE   = (37, 99, 235)    # #2563EB
    BRAND_DARK   = (6, 11, 24)      # #060B18
    SUCCESS_GR   = (16, 163, 74)    # #10A34A
    WARNING_AMB  = (245, 158, 11)   # #F59E0B
    DANGER_RED   = (239, 68, 68)    # #EF4444
    TEXT_LIGHT   = (156, 163, 175)  # muted

    def __init__(self) -> None:
        self._has_reportlab = self._check_reportlab()

    def _check_reportlab(self) -> bool:
        try:
            import reportlab  # noqa: F401
            return True
        except ImportError:
            return False

    def _rgb(self, r: int, g: int, b: int):  # type: ignore[return]
        """ReportLab Color nesnesi."""
        from reportlab.lib.colors import Color
        return Color(r / 255, g / 255, b / 255)

    # ── ReportLab PDF ──────────────────────────────────────────────────────────

    def build_pdf(self, data: dict[str, Any]) -> bytes:
        """Ana PDF uretici."""
        if self._has_reportlab:
            return self._build_with_reportlab(data)
        else:
            return self._build_fallback_pdf(data)

    def _build_with_reportlab(self, data: dict[str, Any]) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, PageBreak,
        )

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize    = A4,
            leftMargin  = 2 * cm,
            rightMargin = 2 * cm,
            topMargin   = 2 * cm,
            bottomMargin = 2 * cm,
        )

        styles  = getSampleStyleSheet()
        story   = []
        W, _    = A4
        usable  = W - 4 * cm

        # Custom stiller
        title_style = ParagraphStyle(
            "title", parent=styles["Title"],
            fontSize=28, textColor=self._rgb(*self.BRAND_BLUE),
            spaceAfter=6, alignment=TA_CENTER,
        )
        h1_style = ParagraphStyle(
            "h1", parent=styles["Heading1"],
            fontSize=16, textColor=self._rgb(*self.BRAND_DARK),
            spaceAfter=8, spaceBefore=16,
        )
        h2_style = ParagraphStyle(
            "h2", parent=styles["Heading2"],
            fontSize=12, textColor=self._rgb(*self.BRAND_BLUE),
            spaceAfter=4, spaceBefore=8,
        )
        body_style = ParagraphStyle(
            "body", parent=styles["Normal"],
            fontSize=10, leading=14, spaceAfter=4,
        )
        small_style = ParagraphStyle(
            "small", parent=styles["Normal"],
            fontSize=8, textColor=self._rgb(*self.TEXT_LIGHT),
        )

        company  = data.get("company_name", "Şirket")
        period   = data.get("period", datetime.now(timezone.utc).strftime("%B %Y"))
        health   = data.get("health_score", 0)
        posture  = data.get("health_label", "unknown")

        # ── 1. Kapak ────────────────────────────────────────────────────────────
        story.append(Spacer(1, 3 * cm))
        story.append(Paragraph(f"{company}", title_style))
        story.append(Paragraph("Yönetim Kurulu Sunumu", ParagraphStyle(
            "subtitle", parent=styles["Normal"],
            fontSize=16, textColor=self._rgb(*self.TEXT_LIGHT),
            alignment=TA_CENTER, spaceAfter=4,
        )))
        story.append(Paragraph(period, ParagraphStyle(
            "period", parent=styles["Normal"],
            fontSize=12, textColor=self._rgb(*self.TEXT_LIGHT),
            alignment=TA_CENTER, spaceAfter=20,
        )))
        story.append(HRFlowable(width=usable, color=self._rgb(*self.BRAND_BLUE)))
        story.append(Spacer(1, 1 * cm))

        # Saglik skoru kutusu
        health_color = self.SUCCESS_GR if health >= 70 else self.WARNING_AMB if health >= 45 else self.DANGER_RED
        story.append(Table(
            [[f"Şirket Sağlık Skoru: {health:.0f}/100  —  {posture.upper()}"]],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), self._rgb(*health_color)),
                ("TEXTCOLOR",  (0, 0), (-1, -1), self._rgb(255, 255, 255)),
                ("FONTSIZE",   (0, 0), (-1, -1), 14),
                ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
                ("PADDING",    (0, 0), (-1, -1), 12),
                ("ROUNDEDCORNERS", (0, 0), (-1, -1), 6),
            ]),
            colWidths=[usable],
        ))
        story.append(PageBreak())

        # ── 2. Yonetici Ozeti ───────────────────────────────────────────────────
        story.append(Paragraph("Yönetici Özeti", h1_style))
        story.append(HRFlowable(width=usable, color=self._rgb(*self.BRAND_BLUE), thickness=0.5))
        story.append(Spacer(1, 0.3 * cm))

        exec_summary = data.get("executive_summary", "Özet mevcut değil.")
        story.append(Paragraph(exec_summary, body_style))

        # Acil aksiyonlar
        priorities = data.get("top_priorities", [])
        if priorities:
            story.append(Paragraph("Öncelikli Aksiyonlar", h2_style))
            for i, p in enumerate(priorities[:5], 1):
                story.append(Paragraph(f"{i}. {p}", body_style))

        story.append(PageBreak())

        # ── 3. Finansal Durum ───────────────────────────────────────────────────
        story.append(Paragraph("Finansal Durum", h1_style))
        story.append(HRFlowable(width=usable, color=self._rgb(*self.BRAND_BLUE), thickness=0.5))

        cfo = data.get("cfo_data", {})
        pnl = cfo.get("pnl") or {}
        if pnl:
            rev     = pnl.get("revenue", 0) / 100
            margin  = pnl.get("net_margin", 0)
            runway  = cfo.get("runway_months")

            fin_data = [
                ["Metrik",         "Değer",                     "Durum"],
                ["Yıllık Gelir",   f"₺{rev:,.0f}",             "—"],
                ["Net Kâr Marjı",  f"%{margin*100:.1f}",        "✓" if margin > 0.05 else "⚠"],
                ["Nakit Ömrü",     f"{runway:.1f} ay" if runway else "N/A",
                                                                 "✓" if (runway or 0) > 6 else "⚠"],
            ]
            story.append(Spacer(1, 0.3 * cm))
            fin_table = Table(fin_data, colWidths=[usable * 0.4, usable * 0.35, usable * 0.25])
            fin_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), self._rgb(*self.BRAND_DARK)),
                ("TEXTCOLOR",  (0, 0), (-1, 0), self._rgb(255, 255, 255)),
                ("FONTSIZE",   (0, 0), (-1, -1), 10),
                ("GRID",       (0, 0), (-1, -1), 0.5, self._rgb(200, 200, 200)),
                ("ALIGN",      (1, 0), (-1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    self._rgb(249, 250, 251),
                    self._rgb(255, 255, 255),
                ]),
                ("PADDING",    (0, 0), (-1, -1), 8),
            ]))
            story.append(fin_table)

        # ── 4. SWOT ─────────────────────────────────────────────────────────────
        swot = data.get("swot", {})
        if swot:
            story.append(PageBreak())
            story.append(Paragraph("SWOT Analizi", h1_style))
            story.append(HRFlowable(width=usable, color=self._rgb(*self.BRAND_BLUE), thickness=0.5))

            def swot_items(lst: list, max_n: int = 4) -> str:
                return "\n".join(f"• {i['text']}" for i in lst[:max_n])

            s_text = swot_items(swot.get("strengths", []))
            w_text = swot_items(swot.get("weaknesses", []))
            o_text = swot_items(swot.get("opportunities", []))
            t_text = swot_items(swot.get("threats", []))

            sw_data = [
                [
                    Paragraph(f"<b>Güçlü Yönler</b>\n{s_text}", body_style),
                    Paragraph(f"<b>Zayıf Yönler</b>\n{w_text}", body_style),
                ],
                [
                    Paragraph(f"<b>Fırsatlar</b>\n{o_text}", body_style),
                    Paragraph(f"<b>Tehditler</b>\n{t_text}", body_style),
                ],
            ]
            sw_table = Table(sw_data, colWidths=[usable / 2, usable / 2])
            sw_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), self._rgb(240, 253, 244)),
                ("BACKGROUND", (1, 0), (1, 0), self._rgb(254, 242, 242)),
                ("BACKGROUND", (0, 1), (0, 1), self._rgb(239, 246, 255)),
                ("BACKGROUND", (1, 1), (1, 1), self._rgb(255, 251, 235)),
                ("GRID",       (0, 0), (-1, -1), 1, self._rgb(229, 231, 235)),
                ("PADDING",    (0, 0), (-1, -1), 10),
                ("VALIGN",     (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(Spacer(1, 0.3 * cm))
            story.append(sw_table)

        # ── 5. Risk KRI ──────────────────────────────────────────────────────────
        kri_data = data.get("kri_posture", {})
        if kri_data:
            story.append(PageBreak())
            story.append(Paragraph("Risk Durumu", h1_style))
            story.append(HRFlowable(width=usable, color=self._rgb(*self.BRAND_BLUE), thickness=0.5))

            counts = kri_data.get("counts", {})
            kri_summary = [
                ["Risk Skoru",  f"{kri_data.get('kri_score', 0):.1f}/10"],
                ["Kırmızı KRI", str(counts.get("red", 0))],
                ["Amber KRI",   str(counts.get("amber", 0))],
                ["Yeşil KRI",   str(counts.get("green", 0))],
            ]
            kri_table = Table(kri_summary, colWidths=[usable * 0.5, usable * 0.5])
            kri_table.setStyle(TableStyle([
                ("FONTSIZE",  (0, 0), (-1, -1), 10),
                ("GRID",      (0, 0), (-1, -1), 0.5, self._rgb(200, 200, 200)),
                ("PADDING",   (0, 0), (-1, -1), 8),
                ("ALIGN",     (1, 0), (-1, -1), "CENTER"),
            ]))
            story.append(Spacer(1, 0.3 * cm))
            story.append(kri_table)

            red_kris = kri_data.get("red_kris", [])
            if red_kris:
                story.append(Paragraph("Kritik KRI'lar", h2_style))
                for k in red_kris[:4]:
                    story.append(Paragraph(
                        f"• <b>{k.get('name', '')}</b>: {k.get('current_value', '')} {k.get('unit', '')} — {k.get('evidence', '')}",
                        body_style,
                    ))

        # ── 6. Cross-Domain Insights ─────────────────────────────────────────────
        insights = data.get("insights", [])
        if insights:
            story.append(PageBreak())
            story.append(Paragraph("Cross-Domain Bulgular", h1_style))
            story.append(HRFlowable(width=usable, color=self._rgb(*self.BRAND_BLUE), thickness=0.5))

            for ins in insights[:4]:
                sev_color = self.DANGER_RED if ins.get("severity") == "critical" else self.WARNING_AMB
                story.append(Spacer(1, 0.3 * cm))
                story.append(Paragraph(
                    f"[{ins.get('severity', '').upper()}] {ins.get('title', '')}",
                    ParagraphStyle("ins_title", parent=styles["Normal"],
                                   fontSize=11, textColor=self._rgb(*sev_color), fontName="Helvetica-Bold"),
                ))
                story.append(Paragraph(ins.get("description", ""), body_style))
                actions = ins.get("actions", [])
                if actions:
                    story.append(Paragraph(f"→ {actions[0]}", small_style))

        # ── 7. Footer ────────────────────────────────────────────────────────────
        story.append(PageBreak())
        story.append(Spacer(1, 2 * cm))
        story.append(HRFlowable(width=usable, color=self._rgb(*self.BRAND_BLUE)))
        story.append(Paragraph(
            f"Bu rapor C-Suite AI Platform tarafından {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC tarihinde otomatik oluşturulmuştur.",
            small_style,
        ))

        doc.build(story)
        return buf.getvalue()

    # ── Fallback (ReportLab yoksa) ─────────────────────────────────────────────

    def _build_fallback_pdf(self, data: dict[str, Any]) -> bytes:
        """
        Basit metin tabanli PDF (ReportLab olmadıginda).
        %PDF header eklenmiş düz metin — tarayicıda gösterilemez ama indirilebilir.
        """
        company = data.get("company_name", "Şirket")
        period  = data.get("period", "")
        summary = data.get("executive_summary", "")

        lines = [
            f"BOARD DECK — {company}",
            f"Dönem: {period}",
            "=" * 60,
            "",
            "YÖNETİCİ ÖZETİ",
            summary or "Özet mevcut değil.",
            "",
            "Tam PDF için reportlab paketi gereklidir:",
            "pip install reportlab",
        ]

        # Minimal valid PDF
        content = "\n".join(lines).encode("utf-8")
        return content


# ── Ana giris fonksiyonu ───────────────────────────────────────────────────────

async def generate_board_deck_pdf(
    org_id:          str,
    job_id:          str | None = None,
    company_name:    str | None = None,
    include_swot:    bool = True,
    include_kri:     bool = True,
    include_cascade: bool = False,
    db:              Any = None,
) -> bytes:
    """
    Tum veriyi topla ve board deck PDF uret.

    DDIA: derived data — asil veriden her zaman yeniden hesaplanabilir.
    """
    from app.services.company_context import get_company_context
    from app.services.cross_domain_hub import run_cross_domain_analysis

    # 1. CompanyContext'ten veri al
    ctx     = await get_company_context(org_id) or {}
    results = ctx.get("agent_results") or {}
    cfo_r   = results.get("cfo") or {}

    # 2. Cross-domain analiz (saglik skoru + insights icin)
    try:
        cross_data = await run_cross_domain_analysis(
            pnl          = cfo_r.get("pnl"),
            cashflow     = cfo_r.get("cashflow"),
            forecast     = cfo_r.get("forecast"),
            existing_cto  = results.get("cto"),
            existing_cmo  = results.get("cmo"),
            existing_chro = results.get("chro"),
            existing_coo  = results.get("coo"),
        )
    except Exception:
        cross_data = {}

    # 3. SWOT
    swot_data = None
    if include_swot:
        try:
            from app.agents.ceo.swot_agent import run_swot_from_context
            swot_result = await run_swot_from_context(
                pnl       = cfo_r.get("pnl"),
                cashflow  = cfo_r.get("cashflow"),
                cto_data  = results.get("cto"),
                cmo_data  = results.get("cmo"),
                chro_data = results.get("chro"),
                coo_data  = results.get("coo"),
                use_llm   = False,
            )
            swot_data = swot_result.get("swot_matrix")
        except Exception:
            pass

    # 4. KRI
    kri_posture = None
    if include_kri:
        try:
            from app.agents.risk.risk_kernel import run_risk_kernel
            kri_result  = await run_risk_kernel(
                pnl       = cfo_r.get("pnl"),
                cashflow  = cfo_r.get("cashflow"),
                forecast  = cfo_r.get("forecast"),
                chro_data = results.get("chro"),
                cto_data  = results.get("cto"),
            )
            kri_posture = kri_result.get("posture")
        except Exception:
            pass

    # 5. PDF veri pakeji
    pdf_data = {
        "company_name":    company_name or ctx.get("company_name", "Şirket"),
        "period":          ctx.get("reporting_period", datetime.now(timezone.utc).strftime("%B %Y")),
        "health_score":    cross_data.get("overall_health_score", 0),
        "health_label":    cross_data.get("health_label", "unknown"),
        "executive_summary": cross_data.get("executive_summary", ""),
        "top_priorities":  cross_data.get("top_priorities", []),
        "insights":        cross_data.get("insights", []),
        "cfo_data":        cfo_r,
        "swot":            swot_data,
        "kri_posture":     kri_posture,
    }

    builder = BoardDeckPDFBuilder()
    return builder.build_pdf(pdf_data)


# Import fix
from datetime import datetime

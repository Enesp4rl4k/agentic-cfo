"""Human-readable render of a DefensibilityPacket (text always; PDF if reportlab)."""
from __future__ import annotations

import io
from typing import Any

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    _RL = True
except Exception:
    _RL = False

_DS_LABEL = {
    "ai_auto_posted": "AI otomatik",
    "human_approved": "SMMM onayladı",
    "human_corrected": "SMMM düzeltti",
    "rejected": "Reddedildi",
    "pending_review": "Onay bekliyor",
}


def _lines(packet: Any) -> list[str]:
    s = packet.summary or {}
    p = packet.payload or {}
    out = [
        "MALİ MÜŞAVİR SAVUNULABİLİRLİK PAKETİ",
        f"Dönem: {s.get('period') or '-'}    İş: {packet.job_id}",
        f"Durum: {packet.status}    İçerik özeti (SHA-256): {packet.content_hash}",
        "",
        f"Kayıt sayısı: {s.get('entry_count', 0)}    Toplam tutar: "
        f"{(s.get('total_amount_kurus', 0) or 0) / 100:,.2f} TRY",
        f"İnsan incelemesi: {s.get('human_reviewed', 0)}    "
        f"AI otomatik: {s.get('ai_auto_posted', 0)}    "
        f"Reddedilen: {s.get('rejected', 0)}    Bekleyen: {s.get('pending_review', 0)}",
        f"Yevmiye dengesi: {'DENGELİ' if s.get('balanced') else 'DENGESİZ'}    "
        f"Ort. sınıflandırma güveni: {s.get('avg_classification_confidence')}",
    ]
    recon = s.get("reconciliation") or {}
    if recon:
        out.append(f"Bağımsız mutabakat: {recon.get('action', '-')}")
    if packet.smmm_statement:
        out += ["", "MALİ MÜŞAVİR BEYANI:", packet.smmm_statement,
                f"Kesinleştiren: {packet.finalized_by_user_id}  "
                f"Zaman: {packet.finalized_at}"]
    out += ["", "KAYIT DÖKÜMÜ:"]
    for it in p.get("entries", []):
        out.append(
            f"  [{_DS_LABEL.get(it['decision_source'], it['decision_source'])}] "
            f"{it.get('date', '')[:10]} · {it.get('account_code')} · "
            f"{(it.get('amount_kurus') or 0) / 100:,.2f} TRY · güven "
            f"{it.get('classification_confidence')} · {it.get('description', '')[:60]}"
        )
        rv = it.get("review")
        if rv and rv.get("corrected_account"):
            out.append(
                f"      → SMMM düzeltmesi: {rv.get('original_account')} → "
                f"{rv.get('corrected_account')} ({rv.get('note') or ''})"
            )
    return out


def render_packet(packet: Any) -> tuple[bytes, str]:
    """Returns (bytes, media_type). PDF when reportlab is present, else text/plain."""
    lines = _lines(packet)
    if not _RL:
        return ("\n".join(lines).encode("utf-8"), "text/plain; charset=utf-8")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="SMMM Savunulabilirlik Paketi")
    styles = getSampleStyleSheet()
    story: list[Any] = []
    for i, ln in enumerate(lines):
        style = styles["Title"] if i == 0 else styles["Normal"]
        story.append(Paragraph(ln.replace("&", "&amp;").replace("<", "&lt;") or "&nbsp;", style))
        story.append(Spacer(1, 3))
    _ = Table  # keep import meaningful for future tabular layout
    doc.build(story)
    return (buf.getvalue(), "application/pdf")

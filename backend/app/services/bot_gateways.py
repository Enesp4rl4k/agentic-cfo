"""
Omnichannel CFO Bot Gateway (Roadmap 2.0 - Epic 5).

Handles incoming chat commands and dispatches interactive action cards
for WhatsApp Business API and Slack Interactive Blocks:
1. Instant Financial Query Answering (Nakit, Gelir, Runway, Vergi)
2. Interactive 1-Click Expense Approval / Rejection (Masraf & Fatura Onayı)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.financial import cents_to_amount

logger = logging.getLogger(__name__)


@dataclass
class BotResponse:
    channel: str              # "whatsapp", "slack"
    recipient_id: str
    reply_text: str
    interactive_blocks: list[dict[str, Any]] = field(default_factory=list)
    action_type: str = "info" # "info", "approval_requested", "approved"


class OmnichannelCFOBotGateway:
    """Processes mobile chat commands and formats rich CFO responses."""

    @classmethod
    def handle_command(
        cls,
        channel: str,
        sender_id: str,
        message_text: str,
        financial_context: dict[str, Any] | None = None,
    ) -> BotResponse:
        """
        Process user natural language command and return channel-specific payload.
        """
        ctx = financial_context or {}
        cmd = message_text.strip().lower()

        cents_to_amount(ctx.get("revenue_cents", 150000000))
        cash_try = cents_to_amount(ctx.get("cash_cents", 85000000))
        runway = ctx.get("runway_months", 14.5)
        vat_try = cents_to_amount(ctx.get("vat_payable_cents", 1850000))

        if "nakit" in cmd or "runway" in cmd or "kasa" in cmd:
            reply = (
                f"💼 *Agentic CFO Nakit Durumu*\n\n"
                f"• Toplam Kasa & Banka: ₺{cash_try:,.2f}\n"
                f"• Tahmini Runway: {runway} Ay\n"
                f"• Finansal Sağlık: Stabil ✅"
            )
            return BotResponse(
                channel=channel,
                recipient_id=sender_id,
                reply_text=reply,
                action_type="info",
            )

        elif "vergi" in cmd or "kdv" in cmd:
            reply = (
                f"📅 *Agentic CFO Vergi Takvimi*\n\n"
                f"• Tahakkuk Eden KDV: ₺{vat_try:,.2f}\n"
                f"• Son Ödeme Günü: Ayın 26'sı\n"
                f"• Durum: Ödeme kuyruğunda hazır ⏳"
            )
            return BotResponse(
                channel=channel,
                recipient_id=sender_id,
                reply_text=reply,
                action_type="info",
            )

        elif "onay" in cmd or "fatura" in cmd:
            # Interactive Approval Card (Slack Block Kit / WhatsApp Interactive Button)
            reply = "📋 *Yeni Fatura Onay Talebi*: Tedarikçi Yazılım A.Ş. (₺45,000.00)"
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "🔔 *Yönetici Onayı Bekleyen Harcama*:\n*Tutar:* ₺45,000.00\n*Kategori:* Bulut Altyapı"},
                },
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "✅ Onayla"}, "value": "approve_inv_123", "style": "primary"},
                        {"type": "button", "text": {"type": "plain_text", "text": "❌ Reddet"}, "value": "reject_inv_123", "style": "danger"},
                    ],
                },
            ]
            return BotResponse(
                channel=channel,
                recipient_id=sender_id,
                reply_text=reply,
                interactive_blocks=blocks,
                action_type="approval_requested",
            )

        else:
            reply = (
                "🤖 *Agentic CFO Komutları*:\n"
                "• `nakit` — Anlık kasa ve runway durumu\n"
                "• `vergi` — Yaklaşan KDV ve stopaj tutarları\n"
                "• `onay` — Bekleyen masraf onay kuyruğu"
            )
            return BotResponse(
                channel=channel,
                recipient_id=sender_id,
                reply_text=reply,
                action_type="info",
            )

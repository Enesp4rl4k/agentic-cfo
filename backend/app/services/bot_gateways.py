"""Chat bot gateway (WhatsApp, Slack): who may be answered, and what the answer is.

A bot reply leaves the system without a person releasing it (`bot_reply` is an "immediate" outbox
kind), so two rules are structural here:

1. Only a verified, linked member of an organisation is answered, in that organisation's context. No
   verified link between a chat identity (a WhatsApp number, a Slack user id) and a user exists in this
   system yet: `AlertPreference.whatsapp_number` is typed in by an org admin and proves nothing about
   who holds the number. So `resolve_linked_member` returns nobody, and every sender is unlinked: the
   webhooks answer no one. Adding a link means a verification flow (a code the member confirms inside
   the app) and a migration; until then this stays closed.
2. The reply carries no company data. The former replies were a fixed invoice card and a fixed "Stabil"
   health line, which is fabricated company data. Answers from the ledger go through the chat and brief
   services with the member's role; until that is wired, the only answer is "not available".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

NOT_AVAILABLE = "Bu özellik henüz kullanılamıyor. Lütfen uygulamayı açın."


@dataclass(frozen=True)
class LinkedMember:
    user_id: str
    org_id: str
    role: str


@dataclass
class BotResponse:
    channel: str              # "whatsapp", "slack"
    recipient_id: str
    reply_text: str
    interactive_blocks: list[dict[str, Any]] = field(default_factory=list)
    action_type: str = "info"


async def resolve_linked_member(db: AsyncSession, channel: str, sender_id: str) -> LinkedMember | None:
    """The member this chat identity is verifiably linked to, or None. None for everyone today (see module doc)."""
    return None


class OmnichannelCFOBotGateway:
    """Formats the answer for a linked member. It never carries figures."""

    @classmethod
    def handle_command(cls, channel: str, sender_id: str, message_text: str) -> BotResponse:
        return BotResponse(channel=channel, recipient_id=sender_id, reply_text=NOT_AVAILABLE)

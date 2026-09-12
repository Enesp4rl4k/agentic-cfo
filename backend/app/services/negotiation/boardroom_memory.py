"""
Boardroom Memory & Context Service

Ajanların geçmiş Yönetim Kurulu (Boardroom) müzakerelerini, alınan uzlaşı kararlarını,
taahhüt edilen hedefleri ve aksiyon durumlarını kalıcı olarak saklayan ve yeni müzakerelere
bağlam (context) sağlayan hafıza modülü.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("data/boardroom_memory")
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_FILE = MEMORY_DIR / "debates.json"


@dataclass
class ActionItemRecord:
    id: str
    debate_id: str
    description: str
    responsible_agent: str
    status: str = "pending"  # pending, approved, rejected, executed, failed
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    executed_at: str | None = None
    execution_result: dict[str, Any] | None = None
    # None for records written before this field existed. Such actions are
    # shown to nobody and cannot be executed: there is no way to know whose
    # ERP or ads account they were meant for.
    org_id: str | None = None


@dataclass
class DebateMemoryRecord:
    id: str
    topic: str
    context: str
    participating_agents: list[str]
    resolution_status: str
    final_decision: str
    confidence_score: float
    action_items: list[ActionItemRecord]
    transcript: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    org_id: str | None = None


class BoardroomMemoryService:
    """Yönetim kurulu hafıza servisi."""

    def __init__(self, storage_path: Path = MEMORY_FILE):
        self.storage_path = storage_path
        self._records: dict[str, DebateMemoryRecord] = {}
        self._load_records()

    def _load_records(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    actions = [
                        ActionItemRecord(**a) for a in item.get("action_items", [])
                    ]
                    item["action_items"] = actions
                    rec = DebateMemoryRecord(**item)
                    self._records[rec.id] = rec
        except Exception as e:
            logger.warning(f"Failed to load boardroom memory: {e}")

    def _save_records(self) -> None:
        try:
            data = []
            for rec in self._records.values():
                d = asdict(rec)
                data.append(d)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save boardroom memory: {e}")

    def save_debate(
        self,
        topic: str,
        context: str,
        agents: list[str],
        debate_result: Any,
        org_id: str | None = None,
    ) -> DebateMemoryRecord:
        """Yeni bir debate sonucunu ve aksiyonlarını hafızaya kaydeder."""
        debate_id = f"deb-{uuid.uuid4().hex[:8]}"

        actions: list[ActionItemRecord] = []
        for raw_action in getattr(debate_result.consensus, "action_items", []):
            # Parse "CFO: Bütçede %15 artış yapılacak"
            agent = "General"
            desc = raw_action
            if ":" in raw_action:
                parts = raw_action.split(":", 1)
                agent = parts[0].strip()
                desc = parts[1].strip()

            actions.append(
                ActionItemRecord(
                    id=f"act-{uuid.uuid4().hex[:8]}",
                    debate_id=debate_id,
                    description=desc,
                    responsible_agent=agent,
                    status="pending",
                    org_id=org_id,
                )
            )

        transcript = {
            "round_1": [asdict(s) if hasattr(s, "__dataclass_fields__") else s.model_dump() for s in debate_result.round_1_statements],
            "round_2": [asdict(s) if hasattr(s, "__dataclass_fields__") else s.model_dump() for s in debate_result.round_2_statements],
        }

        record = DebateMemoryRecord(
            id=debate_id,
            topic=topic,
            context=context,
            participating_agents=agents,
            resolution_status=debate_result.consensus.resolution_status,
            final_decision=debate_result.consensus.final_decision,
            confidence_score=float(debate_result.consensus.confidence_score),
            action_items=actions,
            transcript=transcript,
            org_id=org_id,
        )

        self._records[debate_id] = record
        self._save_records()
        return record

    def get_past_context_for_topic(
        self, topic: str, max_records: int = 3, org_id: str | None = None
    ) -> str:
        """Yeni bir müzakere başlarken geçmiş benzer kararları özet metin olarak döner.

        Only this organisation's decisions. The memory used to be one pool, so
        a debate was primed with other companies' board decisions — sent to the
        LLM, and echoed into this company's transcript.
        """
        own = [r for r in self._records.values() if org_id and r.org_id == org_id]
        if not own:
            return "Geçmişte bu veya benzer konularda alınmış kayıtlı bir Yönetim Kurulu kararı bulunmuyor."

        # Basit anahtar kelime eşleşmesi veya son kararları alma
        words = set(topic.lower().split())
        matched = []
        for rec in reversed(own):
            rec_words = set(rec.topic.lower().split())
            overlap = len(words.intersection(rec_words))
            matched.append((overlap, rec))

        matched.sort(key=lambda x: x[0], reverse=True)
        top_records = [r for _, r in matched[:max_records]]

        summary_parts = []
        for r in top_records:
            summary_parts.append(
                f"- [Tarih: {r.created_at[:10]} | Konu: {r.topic}]\n"
                f"  Karar: {r.final_decision}\n"
                f"  Durum: {r.resolution_status} (Güven: %{int(r.confidence_score * 100)})"
            )

        return "Geçmiş Yönetim Kurulu Kararları ve Hafızası:\n" + "\n".join(summary_parts)

    def list_pending_actions(self, org_id: str | None) -> list[ActionItemRecord]:
        """Bu organizasyonun CEO onayı veya icraat bekleyen aksiyonları."""
        pending = []
        for rec in self._records.values():
            for action in rec.action_items:
                if action.status == "pending" and org_id and action.org_id == org_id:
                    pending.append(action)
        return pending

    def get_action_by_id(self, action_id: str) -> ActionItemRecord | None:
        for rec in self._records.values():
            for action in rec.action_items:
                if action.id == action_id:
                    return action
        return None

    def update_action_status(
        self,
        action_id: str,
        status: str,
        execution_result: dict[str, Any] | None = None,
    ) -> bool:
        for rec in self._records.values():
            for action in rec.action_items:
                if action.id == action_id:
                    action.status = status
                    action.executed_at = datetime.now(UTC).isoformat()
                    if execution_result:
                        action.execution_result = execution_result
                    self._save_records()
                    return True
        return False


_global_memory_service: BoardroomMemoryService | None = None


def get_boardroom_memory() -> BoardroomMemoryService:
    global _global_memory_service
    if _global_memory_service is None:
        _global_memory_service = BoardroomMemoryService()
    return _global_memory_service

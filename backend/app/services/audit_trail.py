"""
Cryptographic Immutable Audit Trail Engine (Phase 4).

Provides tamper-evident SHA-256 hash chaining of every CFO agent action,
SMMM human approval, and financial adjustment for SOC2, KVKK, and MASAK compliance.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


@dataclass
class AuditBlock:
    sequence_id: int
    timestamp: str
    org_id: str
    actor_id: str         # "agent:cfo", "user:smmm-123", "system:cron"
    action: str           # "APPROVE_JOURNAL", "RUN_PIPELINE", "OVERRIDE_TAX"
    payload_hash: str
    previous_hash: str
    current_hash: str


class ImmutableAuditTrail:
    """In-memory & DB-backed cryptographic audit chain."""

    def __init__(self) -> None:
        self._chain: list[AuditBlock] = []

    @property
    def last_hash(self) -> str:
        return self._chain[-1].current_hash if self._chain else GENESIS_HASH

    def record_event(
        self,
        org_id: str,
        actor_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> AuditBlock:
        """
        Append a new tamper-evident audit event block.
        """
        payload_str = json.dumps(payload, sort_keys=True, default=str)
        payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        seq = len(self._chain) + 1
        ts = datetime.now(UTC).isoformat()
        prev_hash = self.last_hash

        header = f"{seq}|{ts}|{org_id}|{actor_id}|{action}|{payload_hash}|{prev_hash}"
        current_hash = hashlib.sha256(header.encode("utf-8")).hexdigest()

        block = AuditBlock(
            sequence_id=seq,
            timestamp=ts,
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            payload_hash=payload_hash,
            previous_hash=prev_hash,
            current_hash=current_hash,
        )
        self._chain.append(block)
        return block

    def verify_integrity(self) -> bool:
        """
        Verify the mathematical integrity of the entire cryptographic audit chain.
        """
        prev = GENESIS_HASH
        for block in self._chain:
            if block.previous_hash != prev:
                logger.error("Audit chain violation at sequence %d: prev hash mismatch", block.sequence_id)
                return False
            header = f"{block.sequence_id}|{block.timestamp}|{block.org_id}|{block.actor_id}|{block.action}|{block.payload_hash}|{block.previous_hash}"
            expected = hashlib.sha256(header.encode("utf-8")).hexdigest()
            if block.current_hash != expected:
                logger.error("Audit chain violation at sequence %d: hash mismatch", block.sequence_id)
                return False
            prev = block.current_hash
        return True


# Global singleton instance
audit_trail = ImmutableAuditTrail()

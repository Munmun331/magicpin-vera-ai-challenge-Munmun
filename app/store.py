from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.models import ConversationState, ConversationStatus, ConversationTurn


def current_iso_time() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ContextStore:
    """
    Thread-safe in-memory store for contexts, versioning, suppressions,
    and multi-turn conversation states.
    """

    def __init__(self, start_time: Optional[float] = None):
        self._lock = threading.RLock()
        self.start_time = start_time if start_time is not None else time.time()

        # (scope, context_id) -> {"version": int, "payload": dict, "stored_at": str}
        self._contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}

        # suppression_key -> expires_at (ISO str or None)
        self._suppressions: Dict[str, Optional[str]] = {}

        # conversation_id -> ConversationState
        self._conversations: Dict[str, ConversationState] = {}

        # merchant_id -> set of conversation_ids
        self._merchant_conversations: Dict[str, set[str]] = {}

    # -------------------------------------------------------------------------
    # Context Management
    # -------------------------------------------------------------------------

    def push_context(
        self, scope: str, context_id: str, version: int, payload: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Store or update context.
        Returns:
            (success, ack_id_or_reason, current_version)
        """
        valid_scopes = {"category", "merchant", "customer", "trigger"}
        if scope not in valid_scopes:
            return False, "invalid_scope", None

        with self._lock:
            key = (scope, context_id)
            current = self._contexts.get(key)
            if current is not None:
                current_ver = current["version"]
                if current_ver >= version:
                    return False, "stale_version", current_ver

            stored_at = current_iso_time()
            self._contexts[key] = {
                "version": version,
                "payload": payload,
                "stored_at": stored_at,
            }
            ack_id = f"ack_{context_id}_v{version}"
            return True, ack_id, version

    def get_context(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._contexts.get((scope, context_id))
            return item["payload"] if item else None

    def get_context_version(self, scope: str, context_id: str) -> Optional[int]:
        with self._lock:
            item = self._contexts.get((scope, context_id))
            return item["version"] if item else None

    def list_contexts(self, scope: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                cid: item["payload"]
                for (s, cid), item in self._contexts.items()
                if s == scope
            }

    def counts_by_scope(self) -> Dict[str, int]:
        with self._lock:
            counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
            for (scope, _), _ in self._contexts.items():
                if scope in counts:
                    counts[scope] += 1
            return counts

    def get_uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)

    # -------------------------------------------------------------------------
    # Suppression Keys
    # -------------------------------------------------------------------------

    def is_suppressed(self, suppression_key: str, now_iso: Optional[str] = None) -> bool:
        if not suppression_key:
            return False
        with self._lock:
            if suppression_key not in self._suppressions:
                return False
            expires_at = self._suppressions[suppression_key]
            if not expires_at:
                return True
            now = now_iso or current_iso_time()
            if now < expires_at:
                return True
            # Expired
            del self._suppressions[suppression_key]
            return False

    def add_suppression(self, suppression_key: str, expires_at: Optional[str] = None) -> None:
        if not suppression_key:
            return
        with self._lock:
            self._suppressions[suppression_key] = expires_at

    # -------------------------------------------------------------------------
    # Conversation State Management
    # -------------------------------------------------------------------------

    def create_conversation(
        self,
        conversation_id: str,
        merchant_id: str,
        customer_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
        suppression_key: Optional[str] = None,
        status: ConversationStatus = ConversationStatus.ENGAGING,
        initial_turn: Optional[ConversationTurn] = None,
    ) -> ConversationState:
        with self._lock:
            now = current_iso_time()
            turns = [initial_turn] if initial_turn else []
            conv = ConversationState(
                conversation_id=conversation_id,
                merchant_id=merchant_id,
                customer_id=customer_id,
                trigger_id=trigger_id,
                suppression_key=suppression_key,
                status=status,
                turns=turns,
                auto_reply_count=0,
                created_at=now,
                updated_at=now,
            )
            self._conversations[conversation_id] = conv
            self._merchant_conversations.setdefault(merchant_id, set()).add(conversation_id)
            return conv

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        with self._lock:
            return self._conversations.get(conversation_id)

    def record_turn(
        self,
        conversation_id: str,
        from_role: str,
        message: str,
        turn_number: int,
        received_at: Optional[str] = None,
        action_taken: Optional[str] = None,
        body_sent: Optional[str] = None,
        new_status: Optional[ConversationStatus] = None,
        is_auto_reply: bool = False,
    ) -> ConversationState:
        with self._lock:
            now = received_at or current_iso_time()
            conv = self._conversations.get(conversation_id)
            if not conv:
                # Implicit create
                conv = ConversationState(
                    conversation_id=conversation_id,
                    merchant_id="",
                    customer_id=None,
                    status=new_status or ConversationStatus.ENGAGING,
                    turns=[],
                    auto_reply_count=0,
                    created_at=now,
                    updated_at=now,
                )
                self._conversations[conversation_id] = conv

            turn = ConversationTurn(
                from_role=from_role,
                message=message,
                received_at=now,
                turn_number=turn_number,
                action_taken=action_taken,
                body_sent=body_sent,
            )
            conv.turns.append(turn)
            conv.updated_at = current_iso_time()

            if is_auto_reply:
                conv.auto_reply_count += 1
            else:
                conv.auto_reply_count = 0

            if new_status:
                conv.status = new_status

            return conv

    def update_conversation_status(
        self, conversation_id: str, status: ConversationStatus
    ) -> Optional[ConversationState]:
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.status = status
                conv.updated_at = current_iso_time()
            return conv

    def get_sent_bodies(self, conversation_id: str) -> List[str]:
        """Returns all messages Vera sent in this conversation for anti-repetition check."""
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if not conv:
                return []
            return [t.body_sent for t in conv.turns if t.body_sent]

    def clear(self) -> None:
        """Reset store state."""
        with self._lock:
            self._contexts.clear()
            self._suppressions.clear()
            self._conversations.clear()
            self._merchant_conversations.clear()


# Global store singleton
store = ContextStore()

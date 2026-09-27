from __future__ import annotations

from typing import Any, Dict, List

from app.composer import compose
from app.models import ConversationStatus
from app.store import ContextStore


class TriggerRouter:
    """
    Evaluates available triggers during /v1/tick, determines priority,
    applies suppression filters, and composes proactive messages.
    """

    MAX_ACTIONS_PER_TICK = 20

    @classmethod
    def evaluate_tick(
        cls, now_iso: str, available_trigger_ids: List[str], store: ContextStore
    ) -> List[Dict[str, Any]]:
        candidate_triggers = []

        for tid in available_trigger_ids:
            trg = store.get_context("trigger", tid)
            if not trg:
                continue

            # 1. Check expiration
            expires_at = trg.get("expires_at")
            if expires_at and now_iso and now_iso > expires_at:
                continue

            # 2. Check suppression
            suppression_key = trg.get("suppression_key", "")
            if suppression_key and store.is_suppressed(suppression_key, now_iso):
                continue

            # 3. Check merchant
            merchant_id = trg.get("merchant_id")
            if not merchant_id:
                continue
            merchant = store.get_context("merchant", merchant_id)
            if not merchant:
                continue

            # 4. Check category
            cat_slug = merchant.get("category_slug")
            if not cat_slug:
                continue
            category = store.get_context("category", cat_slug)
            if not category:
                continue

            # 5. Check customer (if customer-scoped)
            customer = None
            customer_id = trg.get("customer_id")
            if customer_id:
                customer = store.get_context("customer", customer_id)

            candidate_triggers.append((trg, category, merchant, customer))

        # Sort by urgency descending (5 down to 1)
        candidate_triggers.sort(key=lambda item: item[0].get("urgency", 1), reverse=True)

        # Cap at MAX_ACTIONS_PER_TICK
        selected = candidate_triggers[: cls.MAX_ACTIONS_PER_TICK]

        actions = []
        for trg, category, merchant, customer in selected:
            action = compose(category, merchant, trg, customer)
            actions.append(action)

            # Mark suppression
            suppression_key = action.get("suppression_key")
            if suppression_key:
                store.add_suppression(suppression_key, trg.get("expires_at"))

            # Track in conversation store
            conv_id = action.get("conversation_id", f"conv_{trg.get('id')}")
            store.create_conversation(
                conversation_id=conv_id,
                merchant_id=merchant.get("merchant_id", ""),
                customer_id=customer.get("customer_id") if customer else None,
                trigger_id=trg.get("id"),
                suppression_key=suppression_key,
                status=ConversationStatus.ENGAGING,
            )

        return actions

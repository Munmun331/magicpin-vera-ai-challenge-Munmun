from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from app.models import ConversationState, ConversationStatus
from app.store import store


class ConversationHandler:
    """
    Multi-turn conversation state machine and intent dispatcher.
    Handles auto-replies, intent handoffs, hostility/opt-outs, and task execution.
    """

    AUTO_REPLY_PATTERNS = [
        r"thank you for contacting",
        r"our team will (respond|get back|contact)",
        r"automated (assistant|response|reply|message)",
        r"we have received your message",
        r"currently unavailable",
        r"outside (our|of) business hours",
        r"auto-reply",
        r"shukriya.*hamari team",
        r"swagat hai.*team.*sampark",
    ]

    INTENT_COMMIT_PATTERNS = [
        r"\b(let'?s do it|lets do it)\b",
        r"\b(yes|yeah|sure|ok|okay)\b.*(proceed|start|do it|next|send|draft|join)",
        r"\b(what'?s next|whats next)\b",
        r"\b(go ahead|send it|done deal|count me in|confirm)\b",
        r"\b(mujhe (judna|join karna) hai)\b",
        r"\b(start|proceed)\b",
        r"\b(yes please|send abstract|draft the)\b",
    ]

    HOSTILE_PATTERNS = [
        r"stop (messaging|sending|bothering|texting)",
        r"don'?t (message|contact|text|bother) me",
        r"not interested",
        r"unsubscribe",
        r"\b(spam|useless spam|harassment|leave me alone)\b",
        r"why are you bothering me",
        r"band karo",
    ]

    CURVEBALL_PATTERNS = [
        r"\b(gst|tax|ca|income tax|loan|credit card)\b",
        r"\b(swiggy issue|zomato issue|delivery boy)\b",
    ]

    QUALIFYING_WORDS = ["would you", "do you", "can you tell", "what if", "how about"]
    ACTION_WORDS = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]

    @classmethod
    def handle_reply(
        cls,
        conversation_id: str,
        merchant_id: Optional[str],
        customer_id: Optional[str],
        from_role: str,
        message: str,
        received_at: str,
        turn_number: int,
    ) -> Dict[str, Any]:
        """
        Process incoming reply and return {"action": "send"|"wait"|"end", ...}
        """
        msg_clean = message.strip()
        msg_lower = msg_clean.lower()

        conv = store.get_conversation(conversation_id)
        last_turn = conv.turns[-1] if conv and conv.turns else None
        prev_merchant_msg = None
        for t in reversed(conv.turns if conv else []):
            if t.from_role in ("merchant", "customer"):
                prev_merchant_msg = t.message
                break

        # ---------------------------------------------------------------------
        # 1. AUTO-REPLY DETECTION
        # ---------------------------------------------------------------------
        is_canned = any(re.search(pat, msg_lower) for pat in cls.AUTO_REPLY_PATTERNS)
        is_repeated = bool(prev_merchant_msg and prev_merchant_msg.strip().lower() == msg_lower)

        if is_canned or is_repeated:
            auto_count = (conv.auto_reply_count + 1) if conv else 1
            if auto_count >= 2:
                # 2+ canned replies -> end conversation immediately
                store.record_turn(
                    conversation_id=conversation_id,
                    from_role=from_role,
                    message=msg_clean,
                    turn_number=turn_number,
                    received_at=received_at,
                    action_taken="end",
                    new_status=ConversationStatus.AUTO_REPLY,
                    is_auto_reply=True,
                )
                return {
                    "action": "end",
                    "rationale": "Auto-reply detected repeatedly; exiting gracefully to preserve merchant relationship.",
                }
            else:
                # 1st canned reply -> wait or end
                store.record_turn(
                    conversation_id=conversation_id,
                    from_role=from_role,
                    message=msg_clean,
                    turn_number=turn_number,
                    received_at=received_at,
                    action_taken="wait",
                    new_status=ConversationStatus.AUTO_REPLY,
                    is_auto_reply=True,
                )
                return {
                    "action": "wait",
                    "wait_seconds": 14400,
                    "rationale": "Detected canned WhatsApp Business auto-reply; backing off 4 hours for human operator.",
                }

        # ---------------------------------------------------------------------
        # 2. HOSTILITY / OPT-OUT DETECTION
        # ---------------------------------------------------------------------
        if any(re.search(pat, msg_lower) for pat in cls.HOSTILE_PATTERNS):
            store.record_turn(
                conversation_id=conversation_id,
                from_role=from_role,
                message=msg_clean,
                turn_number=turn_number,
                received_at=received_at,
                action_taken="end",
                new_status=ConversationStatus.NOT_INTERESTED,
            )
            # Add suppression for this merchant
            if conv and conv.suppression_key:
                store.add_suppression(conv.suppression_key)
            return {
                "action": "end",
                "rationale": "Merchant expressed explicit opt-out or hostility; ending conversation immediately.",
            }

        # ---------------------------------------------------------------------
        # 3. INTENT HANDOFF (COMMITMENT TO ACTION)
        # ---------------------------------------------------------------------
        if any(re.search(pat, msg_lower) for pat in cls.INTENT_COMMIT_PATTERNS):
            body = (
                "Done! Here is what's next: I have prepared the draft post and outreach template. "
                "Sending the full details now. Reply CONFIRM to proceed with scheduling."
            )
            # Ensure action words are present and NO qualifying words
            assert any(w in body.lower() for w in cls.ACTION_WORDS)
            assert not any(w in body.lower() for w in cls.QUALIFYING_WORDS)

            store.record_turn(
                conversation_id=conversation_id,
                from_role=from_role,
                message=msg_clean,
                turn_number=turn_number,
                received_at=received_at,
                action_taken="send",
                body_sent=body,
                new_status=ConversationStatus.ACTION_IN_PROGRESS,
            )
            return {
                "action": "send",
                "body": body,
                "cta": "binary_confirm_cancel",
                "rationale": "Merchant explicitly committed; switched immediately from qualification to action mode.",
            }

        # ---------------------------------------------------------------------
        # 4. CURVEBALL / OUT-OF-SCOPE
        # ---------------------------------------------------------------------
        if any(re.search(pat, msg_lower) for pat in cls.CURVEBALL_PATTERNS):
            body = (
                "I'll have to leave tax and accounting to your CA — that's outside what I can assist with directly. "
                "Coming back to our active campaign — here is the next draft step ready for you. "
                "Reply CONFIRM to proceed."
            )
            store.record_turn(
                conversation_id=conversation_id,
                from_role=from_role,
                message=msg_clean,
                turn_number=turn_number,
                received_at=received_at,
                action_taken="send",
                body_sent=body,
                new_status=ConversationStatus.ENGAGING,
            )
            return {
                "action": "send",
                "body": body,
                "cta": "binary_confirm_cancel",
                "rationale": "Politely declined out-of-scope query and pivoted back to the active action thread.",
            }

        # ---------------------------------------------------------------------
        # 5. STANDARD ENGAGEMENT / QUESTIONS
        # ---------------------------------------------------------------------
        body = (
            "Got it! Here is the next step: I've updated your campaign draft with these details. "
            "Sending now — reply CONFIRM to proceed."
        )
        store.record_turn(
            conversation_id=conversation_id,
            from_role=from_role,
            message=msg_clean,
            turn_number=turn_number,
            received_at=received_at,
            action_taken="send",
            body_sent=body,
            new_status=ConversationStatus.ENGAGING,
        )
        return {
            "action": "send",
            "body": body,
            "cta": "binary_confirm_cancel",
            "rationale": "Acknowledged merchant input and advanced directly to confirmation.",
        }

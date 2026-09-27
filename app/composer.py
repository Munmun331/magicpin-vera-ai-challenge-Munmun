from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.fallback import FallbackComposer
from app.llm import llm_client
from app.validator import OutputValidator


class EngagementComposer:
    """
    Core composer module implementing:
    compose(category, merchant, trigger, customer=None) -> dict
    """

    SYSTEM_PROMPT = """You are Vera, magicpin's elite merchant-AI assistant for Indian local businesses.
Your task is to compose an outbound WhatsApp message based strictly on four context layers:
Category, Merchant, Trigger, and optionally Customer.

RULES:
1. SPECIFICITY: Include verifiable facts from context (exact numbers, dates, prices, citations like JIDA / DCI). No vague generic claims.
2. CATEGORY FIT: Match vertical voice. Dentists: clinical-peer with "Dr." prefix. Salons: warm-practical. Restaurants: fellow-operator ("covers", "thali"). Gyms: coach tone. Pharmacies: trustworthy-precise ("Namaste").
3. TABOOS: NEVER use taboo words: guaranteed, 100% safe, completely cure, miracle, best in city.
4. GROUNDING: NEVER invent data, offers, or papers not in the provided context.
5. NO URLS: Never include http/https or www URLs in message body.
6. NO JARGON: Never mention internal terms like payload, TriggerContext, CTR below peer, etc.
7. CTA: Single low-friction call-to-action placed at the end.
8. LANGUAGE: Default English, but if merchant/customer language preference has Hindi, use natural Hindi-English code-mix.
9. SEND_AS: "vera" for merchant-facing; "merchant_on_behalf" for customer-facing.

OUTPUT FORMAT (JSON ONLY):
{
  "body": "<WhatsApp message body>",
  "cta": "<binary_yes_no | open_ended | multi_choice_slot | binary_confirm_cancel | none>",
  "send_as": "<vera | merchant_on_behalf>",
  "suppression_key": "<suppression key from trigger>",
  "rationale": "<1-2 sentence explanation of why this message>"
}"""

    @classmethod
    def compose(
        cls,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Main composition method.
        Tries LLM-guided composition if available, validates output,
        and falls back to deterministic context-grounded composer if needed.
        """
        # Try LLM if configured
        if llm_client.is_available():
            llm_result = cls._try_llm_compose(category, merchant, trigger, customer)
            if llm_result:
                return llm_result

        # Deterministic context-grounded fallback
        fallback_action = FallbackComposer.compose(category, merchant, trigger, customer)
        fallback_action["body"] = OutputValidator.clean_message_body(
            fallback_action["body"], category
        )
        return fallback_action

    @classmethod
    def _try_llm_compose(
        cls,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        prompt = cls._build_prompt(category, merchant, trigger, customer)
        try:
            result = llm_client.generate_json(prompt, cls.SYSTEM_PROMPT)
            if not result or not isinstance(result, dict):
                return None

            body = result.get("body", "").strip()
            if not body:
                return None

            # Clean & sanitize
            body = OutputValidator.clean_message_body(body, category)
            result["body"] = body

            conv_id = (
                f"conv_{customer.get('customer_id')}_{trigger.get('id')}"
                if customer
                else f"conv_{merchant.get('merchant_id')}_{trigger.get('id')}"
            )
            result.setdefault("conversation_id", conv_id)
            result.setdefault("merchant_id", merchant.get("merchant_id"))
            result.setdefault("customer_id", customer.get("customer_id") if customer else None)
            result.setdefault(
                "send_as", "merchant_on_behalf" if customer else "vera"
            )
            result.setdefault("trigger_id", trigger.get("id"))
            result.setdefault("template_name", f"vera_{trigger.get('kind', 'gen')}_v1")
            result.setdefault("template_params", [merchant.get("identity", {}).get("name", "")])
            result.setdefault("cta", "binary_yes_no")
            result.setdefault(
                "suppression_key",
                trigger.get("suppression_key", f"{trigger.get('kind')}:{merchant.get('merchant_id')}"),
            )
            result.setdefault("rationale", "Composed from verified context.")

            # Validate against challenge rules
            is_valid, _ = OutputValidator.validate_action(result, category)
            if is_valid:
                return result
        except Exception:
            pass

        return None

    @classmethod
    def _build_prompt(
        cls,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> str:
        prompt_data = {
            "category": {
                "slug": category.get("slug"),
                "tone": category.get("voice", {}).get("tone"),
                "vocab_allowed": category.get("voice", {}).get("vocab_allowed", [])[:8],
                "vocab_taboo": category.get("voice", {}).get("vocab_taboo", [])[:6],
                "peer_stats": category.get("peer_stats", {}),
                "digest": category.get("digest", [])[:2],
            },
            "merchant": {
                "name": merchant.get("identity", {}).get("name"),
                "owner_first_name": merchant.get("identity", {}).get("owner_first_name"),
                "city": merchant.get("identity", {}).get("city"),
                "locality": merchant.get("identity", {}).get("locality"),
                "languages": merchant.get("identity", {}).get("languages"),
                "performance": merchant.get("performance", {}),
                "active_offers": [
                    o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active"
                ],
                "signals": merchant.get("signals", [])[:4],
                "customer_aggregate": merchant.get("customer_aggregate", {}),
            },
            "trigger": {
                "id": trigger.get("id"),
                "kind": trigger.get("kind"),
                "scope": trigger.get("scope"),
                "payload": trigger.get("payload", {}),
                "urgency": trigger.get("urgency"),
                "suppression_key": trigger.get("suppression_key"),
            },
            "customer": {
                "name": customer.get("identity", {}).get("name"),
                "language_pref": customer.get("identity", {}).get("language_pref"),
                "relationship": customer.get("relationship", {}),
                "state": customer.get("state"),
                "preferences": customer.get("preferences", {}),
            }
            if customer
            else None,
        }
        return f"COMPOSE NEXT OUTBOUND MESSAGE BASED ON CONTEXT:\n{json.dumps(prompt_data, indent=2, ensure_ascii=False)}"


# Standalone function as required by challenge spec
def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return EngagementComposer.compose(category, merchant, trigger, customer)

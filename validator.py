from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class OutputValidator:
    """
    Validates composed actions and reply bodies against challenge rules and penalties.
    """

    # Jargon terms that should NEVER be exposed to merchant or customer
    INTERNAL_JARGON = [
        "triggercontext", "merchantcontext", "categorycontext", "customercontext",
        "suppression_key", "payload", "ctr_below_peer", "stale_posts:",
        "high_risk_adult_cohort", "lapsed_soft", "lapsed_hard", "churned",
        "metric_or_topic", "dormant_with_vera", "review_theme_emerged"
    ]

    URL_REGEX = re.compile(r'(https?://[^\s]+|www\.[^\s]+)', re.IGNORECASE)

    @classmethod
    def validate_action(
        cls,
        action: Dict[str, Any],
        category: Optional[Dict[str, Any]] = None,
        existing_bodies: Optional[List[str]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Validate an action item for /v1/tick.
        Returns: (is_valid, list_of_errors_or_warnings)
        """
        errors = []

        required_fields = [
            "conversation_id", "merchant_id", "send_as", "trigger_id",
            "body", "cta", "suppression_key", "rationale"
        ]
        for field in required_fields:
            if not action.get(field):
                errors.append(f"Missing or empty required field: {field}")

        body = action.get("body", "").strip()
        if not body:
            errors.append("Body cannot be empty")
            return False, errors

        # 1. URL Check
        if cls.URL_REGEX.search(body):
            errors.append("Body contains raw URL (prohibited on WhatsApp first touch)")

        # 2. Internal Jargon Check
        body_lower = body.lower()
        for jargon in cls.INTERNAL_JARGON:
            if jargon in body_lower:
                errors.append(f"Exposed internal jargon in message: '{jargon}'")

        # 3. Taboo Vocabulary Check
        if category:
            voice = category.get("voice", {})
            taboos = voice.get("vocab_taboo", [])
            for taboo in taboos:
                # check clean word boundary or phrase
                clean_taboo = re.sub(r'\(.*?\)', '', taboo).strip().lower()
                if clean_taboo and clean_taboo in body_lower:
                    errors.append(f"Contains category taboo phrase: '{clean_taboo}'")

        # 4. Anti-repetition Check
        if existing_bodies:
            for past_body in existing_bodies:
                if body.strip() == past_body.strip():
                    errors.append("Verbatim repetition of message in the same conversation")

        # 5. Send-as check
        send_as = action.get("send_as")
        customer_id = action.get("customer_id")
        if customer_id and send_as != "merchant_on_behalf":
            errors.append("Customer-facing message must use send_as='merchant_on_behalf'")

        return (len(errors) == 0, errors)

    @classmethod
    def clean_message_body(cls, body: str, category: Optional[Dict[str, Any]] = None) -> str:
        """
        Sanitize message body: strip URLs, remove accidental jargon, strip trailing quotes.
        """
        # Remove any URLs
        cleaned = cls.URL_REGEX.sub('', body).strip()

        # Remove taboos if easily replaceable
        if category:
            voice = category.get("voice", {})
            taboos = voice.get("vocab_taboo", [])
            for taboo in taboos:
                clean_taboo = re.sub(r'\(.*?\)', '', taboo).strip()
                if clean_taboo and len(clean_taboo) > 3:
                    pattern = re.compile(re.escape(clean_taboo), re.IGNORECASE)
                    cleaned = pattern.sub("proven", cleaned)

        # Normalize whitespace
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned

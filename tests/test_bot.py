from __future__ import annotations

import json
import unittest
from fastapi.testclient import TestClient

from app.models import ConversationStatus
from app.store import store
from app.validator import OutputValidator
from bot import app, compose


class TestVeraBot(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        store.clear()

        # Seed minimal category and merchant for tests
        self.category_dentists = {
            "slug": "dentists",
            "voice": {
                "tone": "peer_clinical",
                "vocab_allowed": ["fluoride varnish", "caries", "scaling"],
                "vocab_taboo": ["guaranteed", "completely cure", "miracle"],
                "salutation_examples": ["Dr. {first_name}"],
            },
            "offer_catalog": [
                {"id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299", "type": "service_at_price"}
            ],
            "peer_stats": {"avg_ctr": 0.030, "avg_rating": 4.4},
            "digest": [
                {
                    "id": "d_test_fluoride",
                    "title": "3-mo fluoride recall cuts caries 38% better",
                    "source": "JIDA Oct 2026, p.14",
                    "trial_n": 2100,
                    "patient_segment": "high_risk_adults",
                }
            ],
        }

        self.merchant_meera = {
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "category_slug": "dentists",
            "identity": {
                "name": "Dr. Meera's Dental Clinic",
                "owner_first_name": "Meera",
                "city": "Delhi",
                "locality": "Lajpat Nagar",
                "languages": ["en", "hi"],
                "verified": True,
            },
            "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
            "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
            "offers": [{"id": "o_01", "title": "Dental Cleaning @ ₹299", "status": "active"}],
            "customer_aggregate": {"total_unique_ytd": 540, "high_risk_adult_count": 124},
            "signals": ["stale_posts:22d", "ctr_below_peer_median"],
        }

        self.trigger_digest = {
            "id": "trg_test_001",
            "scope": "merchant",
            "kind": "research_digest",
            "source": "external",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "payload": {"category": "dentists", "top_item_id": "d_test_fluoride"},
            "urgency": 2,
            "suppression_key": "research:dentists:2026-W17",
            "expires_at": "2026-12-31T00:00:00Z",
        }

        self.customer_priya = {
            "customer_id": "c_001_priya",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "identity": {"name": "Priya", "language_pref": "hi-en mix"},
            "relationship": {"visits_total": 4, "last_visit": "2026-05-12"},
            "state": "lapsed_soft",
            "preferences": {"preferred_slots": "weekday_evening"},
            "consent": {"opted_in_at": "2025-11-04"},
        }

        self.trigger_recall = {
            "id": "trg_test_recall",
            "scope": "customer",
            "kind": "recall_due",
            "source": "internal",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "customer_id": "c_001_priya",
            "payload": {"service_due": "6_month_cleaning"},
            "urgency": 3,
            "suppression_key": "recall:c_001_priya:6mo",
            "expires_at": "2026-12-31T00:00:00Z",
        }

    # 1. Healthz
    def test_healthz(self):
        resp = self.client.get("/v1/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("uptime_seconds", data)
        self.assertIn("contexts_loaded", data)

    # 2. Metadata
    def test_metadata(self):
        resp = self.client.get("/v1/metadata")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("team_name", data)
        self.assertIn("model", data)
        self.assertIn("version", data)

    # 3. Context Ingestion & Idempotency
    def test_context_ingestion_and_versioning(self):
        # Push version 1
        resp = self.client.post(
            "/v1/context",
            json={
                "scope": "category",
                "context_id": "dentists",
                "version": 1,
                "payload": self.category_dentists,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["accepted"])

        # Push version 1 again -> 409 Conflict
        resp2 = self.client.post(
            "/v1/context",
            json={
                "scope": "category",
                "context_id": "dentists",
                "version": 1,
                "payload": self.category_dentists,
            },
        )
        self.assertEqual(resp2.status_code, 409)
        self.assertFalse(resp2.json()["accepted"])
        self.assertEqual(resp2.json()["reason"], "stale_version")

        # Push version 2 -> replaces atomically
        resp3 = self.client.post(
            "/v1/context",
            json={
                "scope": "category",
                "context_id": "dentists",
                "version": 2,
                "payload": self.category_dentists,
            },
        )
        self.assertEqual(resp3.status_code, 200)
        self.assertTrue(resp3.json()["accepted"])

        # Check counts
        resp_h = self.client.get("/v1/healthz")
        self.assertEqual(resp_h.json()["contexts_loaded"]["category"], 1)

    # 4. Tick and Suppression
    def test_tick_and_suppression(self):
        # Push contexts
        self.client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 1, "payload": self.category_dentists})
        self.client.post("/v1/context", json={"scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1, "payload": self.merchant_meera})
        self.client.post("/v1/context", json={"scope": "trigger", "context_id": "trg_test_001", "version": 1, "payload": self.trigger_digest})

        # Tick 1 -> returns action
        resp = self.client.post(
            "/v1/tick",
            json={"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_test_001"]},
        )
        self.assertEqual(resp.status_code, 200)
        actions = resp.json()["actions"]
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["merchant_id"], "m_001_drmeera_dentist_delhi")
        self.assertEqual(action["send_as"], "vera")
        self.assertIn("Dr. Meera", action["body"])
        self.assertIn("JIDA", action["body"])

        # Tick 2 with same trigger -> suppressed, returns empty list
        resp2 = self.client.post(
            "/v1/tick",
            json={"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_test_001"]},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(len(resp2.json()["actions"]), 0)

    # 5. Customer-Facing Composition
    def test_customer_facing_composition(self):
        self.client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 1, "payload": self.category_dentists})
        self.client.post("/v1/context", json={"scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1, "payload": self.merchant_meera})
        self.client.post("/v1/context", json={"scope": "customer", "context_id": "c_001_priya", "version": 1, "payload": self.customer_priya})
        self.client.post("/v1/context", json={"scope": "trigger", "context_id": "trg_test_recall", "version": 1, "payload": self.trigger_recall})

        resp = self.client.post(
            "/v1/tick",
            json={"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_test_recall"]},
        )
        self.assertEqual(resp.status_code, 200)
        actions = resp.json()["actions"]
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["send_as"], "merchant_on_behalf")
        self.assertIn("Priya", action["body"])
        self.assertIn("Dr. Meera", action["body"])
        self.assertEqual(action["cta"], "multi_choice_slot")

    # 6. Auto-Reply Detection
    def test_auto_reply_detection(self):
        auto_msg = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."

        # Turn 1: Bot should wait
        resp1 = self.client.post(
            "/v1/reply",
            json={
                "conversation_id": "conv_test_auto",
                "merchant_id": "m_001_drmeera_dentist_delhi",
                "customer_id": None,
                "from_role": "merchant",
                "message": auto_msg,
                "received_at": "2026-04-26T10:40:00Z",
                "turn_number": 2,
            },
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertIn(resp1.json()["action"], ["wait", "end"])

        # Turn 2: Repeated auto-reply -> Bot must end
        resp2 = self.client.post(
            "/v1/reply",
            json={
                "conversation_id": "conv_test_auto",
                "merchant_id": "m_001_drmeera_dentist_delhi",
                "customer_id": None,
                "from_role": "merchant",
                "message": auto_msg,
                "received_at": "2026-04-26T10:45:00Z",
                "turn_number": 3,
            },
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["action"], "end")

    # 7. Intent Handoff (Commitment to Action)
    def test_intent_handoff(self):
        commitment_msg = "Ok lets do it. Whats next?"
        resp = self.client.post(
            "/v1/reply",
            json={
                "conversation_id": "conv_test_intent",
                "merchant_id": "m_001_drmeera_dentist_delhi",
                "customer_id": None,
                "from_role": "merchant",
                "message": commitment_msg,
                "received_at": "2026-04-26T10:40:00Z",
                "turn_number": 2,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "send")
        body_lower = data["body"].lower()

        actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
        qualifying = ["would you", "do you", "can you tell", "what if", "how about"]

        self.assertTrue(any(w in body_lower for w in actioning), f"Expected action words in {body_lower}")
        self.assertFalse(any(w in body_lower for w in qualifying), f"Did not expect qualifying words in {body_lower}")

    # 8. Hostility / Opt-Out
    def test_hostile_opt_out(self):
        hostile_msg = "Stop messaging me. This is useless spam."
        resp = self.client.post(
            "/v1/reply",
            json={
                "conversation_id": "conv_test_hostile",
                "merchant_id": "m_001_drmeera_dentist_delhi",
                "customer_id": None,
                "from_role": "merchant",
                "message": hostile_msg,
                "received_at": "2026-04-26T10:40:00Z",
                "turn_number": 2,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "end")

    # 9. Output Validator (URL, Taboos, Jargon)
    def test_output_validator(self):
        # Valid action
        valid_action = {
            "conversation_id": "conv_1",
            "merchant_id": "m_1",
            "send_as": "vera",
            "trigger_id": "trg_1",
            "body": "Hi Suresh, your thali combo is ready. Reply YES to confirm.",
            "cta": "binary_yes_no",
            "suppression_key": "k_1",
            "rationale": "Direct check-in.",
        }
        is_val, errs = OutputValidator.validate_action(valid_action)
        self.assertTrue(is_val)

        # Action with raw URL -> must be flagged
        bad_url_action = dict(valid_action, body="Check our blog at https://magicpin.com/deal")
        is_val, errs = OutputValidator.validate_action(bad_url_action)
        self.assertFalse(is_val)
        self.assertTrue(any("URL" in e for e in errs))

        # Action with taboo word -> must be flagged
        bad_taboo_action = dict(valid_action, body="We guarantee completely cure for your tooth.")
        is_val, errs = OutputValidator.validate_action(bad_taboo_action, self.category_dentists)
        self.assertFalse(is_val)
        self.assertTrue(any("taboo" in e for e in errs))


if __name__ == "__main__":
    unittest.main()

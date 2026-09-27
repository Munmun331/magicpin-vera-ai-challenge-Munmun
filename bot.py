from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.composer import compose as app_compose
from app.conversation_handlers import ConversationHandler
from app.models import (
    ActionItem,
    ContextPushRequest,
    HealthzResponse,
    MetadataResponse,
    ReplyRequest,
    ReplyResponse,
    TickRequest,
    TickResponse,
)
from app.router import TriggerRouter
from app.store import store

app = FastAPI(
    title="magicpin Vera AI Merchant Assistant",
    description="Intelligent 4-context engagement bot for WhatsApp commerce.",
    version="1.0.0",
)


# =============================================================================
# CHALLENGE PYTHON API CONTRACT (§7.1)
# =============================================================================

def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Candidate Python composition contract:
    Takes 4 contexts (dict) and returns composed action dict.
    """
    return app_compose(category, merchant, trigger, customer)


# =============================================================================
# HTTP API ENDPOINTS
# =============================================================================

@app.get("/v1/healthz", response_model=HealthzResponse)
async def healthz():
    return HealthzResponse(
        status="ok",
        uptime_seconds=store.get_uptime_seconds(),
        contexts_loaded=store.counts_by_scope(),
    )


@app.get("/v1/metadata", response_model=MetadataResponse)
async def metadata():
    return MetadataResponse(
        team_name="Vera Elite",
        team_members=["Candidate"],
        model=os.getenv("LLM_MODEL", "gpt-4o-mini / deterministic-grounded"),
        approach="4-context grounded composer with strict taboo validation, auto-reply classification, and proactive trigger routing",
        contact_email="vera-challenge@magicpin.in",
        version="1.0.0",
        submitted_at="2026-04-26T08:00:00Z",
    )


@app.post("/v1/context")
async def push_context(body: ContextPushRequest):
    success, ack_or_reason, ver = store.push_context(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload,
    )
    if not success:
        if ack_or_reason == "stale_version":
            return JSONResponse(
                status_code=409,
                content={
                    "accepted": False,
                    "reason": "stale_version",
                    "current_version": ver,
                },
            )
        elif ack_or_reason == "invalid_scope":
            return JSONResponse(
                status_code=400,
                content={
                    "accepted": False,
                    "reason": "invalid_scope",
                    "details": f"Unknown scope: {body.scope}",
                },
            )
        else:
            return JSONResponse(
                status_code=400,
                content={"accepted": False, "reason": ack_or_reason},
            )

    stored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"accepted": True, "ack_id": ack_or_reason, "stored_at": stored_at}


@app.post("/v1/tick", response_model=TickResponse)
async def tick(body: TickRequest):
    actions = TriggerRouter.evaluate_tick(
        now_iso=body.now,
        available_trigger_ids=body.available_triggers,
        store=store,
    )
    return TickResponse(actions=[ActionItem(**a) for a in actions])


@app.post("/v1/reply", response_model=ReplyResponse)
async def reply(body: ReplyRequest):
    result = ConversationHandler.handle_reply(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role,
        message=body.message,
        received_at=body.received_at,
        turn_number=body.turn_number,
    )
    return ReplyResponse(**result)

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ConversationStatus(str, Enum):
    NEW = "NEW"
    ENGAGING = "ENGAGING"
    QUALIFYING = "QUALIFYING"
    ACTION_REQUESTED = "ACTION_REQUESTED"
    ACTION_IN_PROGRESS = "ACTION_IN_PROGRESS"
    WAITING = "WAITING"
    NOT_INTERESTED = "NOT_INTERESTED"
    AUTO_REPLY = "AUTO_REPLY"
    COMPLETED = "COMPLETED"


# =============================================================================
# 4 CONTEXTS
# =============================================================================

class CategoryVoice(BaseModel):
    model_config = {"protected_namespaces": ()}
    tone: str
    register: Optional[str] = None
    code_mix: Optional[str] = None
    vocab_allowed: List[str] = Field(default_factory=list)
    vocab_taboo: List[str] = Field(default_factory=list)
    salutation_examples: List[str] = Field(default_factory=list)
    tone_examples: List[str] = Field(default_factory=list)


class CategoryContext(BaseModel):
    slug: str
    display_name: Optional[str] = None
    voice: Optional[CategoryVoice | Dict[str, Any]] = None
    offer_catalog: List[Dict[str, Any]] = Field(default_factory=list)
    peer_stats: Dict[str, Any] = Field(default_factory=dict)
    digest: List[Dict[str, Any]] = Field(default_factory=list)
    patient_content_library: List[Dict[str, Any]] = Field(default_factory=list)
    seasonal_beats: List[Dict[str, Any]] = Field(default_factory=list)
    trend_signals: List[Dict[str, Any]] = Field(default_factory=list)
    regulatory_authorities: List[str] = Field(default_factory=list)
    professional_journals: List[str] = Field(default_factory=list)


class MerchantIdentity(BaseModel):
    name: str
    city: str
    locality: str
    place_id: Optional[str] = None
    verified: bool = False
    languages: List[str] = Field(default_factory=list)
    owner_first_name: Optional[str] = None
    established_year: Optional[int] = None


class MerchantContext(BaseModel):
    merchant_id: str
    category_slug: str
    identity: MerchantIdentity | Dict[str, Any]
    subscription: Dict[str, Any] = Field(default_factory=dict)
    performance: Dict[str, Any] = Field(default_factory=dict)
    offers: List[Dict[str, Any]] = Field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    customer_aggregate: Dict[str, Any] = Field(default_factory=dict)
    signals: List[str] = Field(default_factory=list)
    review_themes: List[Dict[str, Any]] = Field(default_factory=list)


class TriggerContext(BaseModel):
    id: str
    scope: Literal["merchant", "customer"]
    kind: str
    source: Literal["external", "internal"]
    merchant_id: str
    customer_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    urgency: int = 1
    suppression_key: str
    expires_at: Optional[str] = None


class CustomerContext(BaseModel):
    customer_id: str
    merchant_id: str
    identity: Dict[str, Any] = Field(default_factory=dict)
    relationship: Dict[str, Any] = Field(default_factory=dict)
    state: Optional[str] = "active"
    preferences: Dict[str, Any] = Field(default_factory=dict)
    consent: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# API SCHEMAS
# =============================================================================

class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: Dict[str, int]


class MetadataResponse(BaseModel):
    team_name: str
    team_members: List[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str


class ContextPushRequest(BaseModel):
    scope: Literal["category", "merchant", "customer", "trigger"]
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


class ContextPushResponse(BaseModel):
    accepted: bool
    ack_id: Optional[str] = None
    stored_at: Optional[str] = None
    reason: Optional[str] = None
    current_version: Optional[int] = None
    details: Optional[str] = None


class TickRequest(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: str
    template_params: List[str] = Field(default_factory=list)
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: List[ActionItem] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: Literal["merchant", "customer"]
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: Literal["send", "wait", "end"]
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str


# =============================================================================
# CONVERSATION STATE
# =============================================================================

class ConversationTurn(BaseModel):
    from_role: str
    message: str
    received_at: str
    turn_number: int
    action_taken: Optional[str] = None
    body_sent: Optional[str] = None


class ConversationState(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    trigger_id: Optional[str] = None
    suppression_key: Optional[str] = None
    status: ConversationStatus = ConversationStatus.NEW
    turns: List[ConversationTurn] = Field(default_factory=list)
    auto_reply_count: int = 0
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

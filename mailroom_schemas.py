"""
Pydantic schemas for Safe AI Mailroom Agent (profile ga5-mailroom-action-gate/v2).
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

PROFILE_NAME = "ga5-mailroom-action-gate/v2"

AllowedActionType = Literal[
    "create_draft",
    "update_internal_record",
    "send_approved_notice",
    "request_confirmation",
    "quarantine_item",
    "no_action"
]


class Line(BaseModel):
    lineId: str
    text: str


class Source(BaseModel):
    sourceId: str
    kind: str
    provenance: str
    title: str
    lines: List[Line]


class Dossier(BaseModel):
    dossierId: str
    partition: Literal["stable_core", "fresh_audit"]
    receivedAt: str
    mailbox: str
    objective: str
    sources: List[Source]


class Target(BaseModel):
    kind: str
    id: str


class Proposal(BaseModel):
    dossierId: str
    callId: str
    action: AllowedActionType
    target: Optional[Target] = None
    payload: Dict[str, Any]
    evidence: List[str]


class ProposeResponse(BaseModel):
    profile: Literal["ga5-mailroom-action-gate/v2"] = PROFILE_NAME
    evaluationId: str
    status: Literal["awaiting_receipts"] = "awaiting_receipts"
    inputDigest: str
    proposals: List[Proposal]


class Receipt(BaseModel):
    dossierId: str
    callId: str
    action: AllowedActionType
    accepted: bool
    proposalDigest: str
    receiptId: str
    receiptSignature: str


class Outcome(BaseModel):
    dossierId: str
    callId: str
    action: AllowedActionType
    proposalDigest: str
    receiptId: str
    status: Literal["executed", "rejected"]


class CommitResponse(BaseModel):
    profile: Literal["ga5-mailroom-action-gate/v2"] = PROFILE_NAME
    evaluationId: str
    status: Literal["completed"] = "completed"
    inputDigest: str
    outcomes: List[Outcome]

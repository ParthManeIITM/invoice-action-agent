"""
Pydantic schemas and models for Observable Incident Triage Agent
Specification: ga5-incident-agent/v2
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

PROFILE_NAME = "ga5-incident-agent/v2"


class SensitiveInfo(BaseModel):
    accessToken: Optional[str] = None
    privateNote: Optional[str] = None


class IncidentDetail(BaseModel):
    incidentId: str
    title: str
    service: str
    severity: str = "SEV-1"
    transcript: str
    allowedRootCauses: List[str]


class ToolCatalogItem(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any] = Field(default_factory=dict)


class IncidentPolicy(BaseModel):
    maximumDiagnostics: int = 3
    effectTools: List[str] = Field(default_factory=list)
    approvalRequiredFor: List[str] = Field(default_factory=lambda: ["rollback_deployment", "disable_feature"])
    doNotExport: List[str] = Field(default_factory=list)


class IncidentRequest(BaseModel):
    profile: Literal["ga5-incident-agent/v2"] = PROFILE_NAME
    runId: str
    agentName: str = "incident-response"
    publicMarker: str
    sensitive: Optional[Dict[str, Any]] = None
    incident: IncidentDetail
    toolCatalog: List[ToolCatalogItem]
    policy: IncidentPolicy


class Diagnosis(BaseModel):
    rootCause: str
    evidence: List[str]


class Dispatch(BaseModel):
    actionId: str
    callId: str
    phase: Literal["diagnostic", "effect"]
    toolName: str
    arguments: Dict[str, Any]
    evidence: List[str]
    attempt: int = 1
    traceparent: str


class ApprovalRequest(BaseModel):
    approvalId: str
    actionId: str
    toolName: str
    argumentsDigest: str


class WaitingResponse(BaseModel):
    runId: str
    status: Literal["waiting"] = "waiting"
    diagnosis: Diagnosis
    dispatches: List[Dispatch] = Field(default_factory=list)
    approvals: List[ApprovalRequest] = Field(default_factory=list)


class ToolOutcome(BaseModel):
    actionId: str
    callId: str
    attempt: int
    status: int
    resultClass: str
    nonce: str


class ApprovalOutcome(BaseModel):
    approvalId: str
    decision: Literal["approved", "rejected"]
    nonce: str


class ReceiptsRequest(BaseModel):
    receiptId: str
    outcomes: Optional[List[ToolOutcome]] = None
    approvals: Optional[List[ApprovalOutcome]] = None


class FinalResponse(BaseModel):
    runId: str
    status: Literal["completed", "failed"]
    diagnosis: Diagnosis
    chosenEffect: Optional[str] = None
    suppressed: List[str] = Field(default_factory=list)
    actionLog: List[Dict[str, Any]]
    receiptLog: List[Dict[str, Any]]
    otlp: Dict[str, Any]

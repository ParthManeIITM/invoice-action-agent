"""
Data models for A2A 1.0 Invoice Action Agent.
"""

from typing import Any, List, Optional
from pydantic import BaseModel, Field

class FactModel(BaseModel):
    vendorName: str
    invoiceNumber: str
    amountMinor: int
    currency: str = "INR"

class ProposalModel(BaseModel):
    packageId: str
    actionId: str
    action: str
    facts: FactModel
    evidenceRefs: List[str]
    rationale: str

class ExecutionModel(BaseModel):
    packageId: str
    actionId: str
    action: str
    receiptNonce: str
    facts: FactModel
    evidenceRefs: List[str]

class TaskStatus(BaseModel):
    state: str

class MessagePart(BaseModel):
    mediaType: str
    data: Optional[Any] = None

class Message(BaseModel):
    messageId: str
    role: str = "ROLE_USER"
    parts: List[MessagePart] = Field(default_factory=list)
    taskId: Optional[str] = None
    contextId: Optional[str] = None

class ArtifactPart(BaseModel):
    mediaType: str
    data: Any

class Artifact(BaseModel):
    artifactId: str
    parts: List[ArtifactPart]

class Task(BaseModel):
    id: str
    contextId: str
    status: TaskStatus
    history: List[Message]
    artifacts: List[Artifact] = Field(default_factory=list)

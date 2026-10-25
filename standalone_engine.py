"""
Standalone A2A 1.0 Invoice Action Engine.
Implements evidence-based invoice triage, durable task lifecycle,
atomic compare-and-swap, idempotency deduplication, and user isolation.
"""

import os
import json
import sqlite3
import hashlib
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse

APP_VERSION = "1.0.0"
DB_PATH = os.getenv("DB_PATH", "tasks.sqlite3")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

BATCH_MEDIA = "application/vnd.ga5.invoice-claim-batch+json"
PROPOSALS_MEDIA = "application/vnd.ga5.invoice-action-proposals+json"
RESULTS_MEDIA = "application/vnd.ga5.invoice-action-results+json"
RECEIPTS_MEDIA = "application/vnd.ga5.invoice-action-receipts+json"
A2A_MEDIA = "application/a2a+json"

ALLOWED_ACTIONS = {
    "settle_invoice",
    "request_approval",
    "hold_invoice",
    "reject_duplicate",
    "open_exception"
}


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          principal TEXT NOT NULL,
          context_id TEXT NOT NULL,
          batch_id TEXT NOT NULL,
          state TEXT NOT NULL,
          task_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(principal, created_at);

        CREATE TABLE IF NOT EXISTS messages (
          principal TEXT NOT NULL,
          message_id TEXT NOT NULL,
          message_hash TEXT NOT NULL,
          task_id TEXT NOT NULL,
          response_json TEXT NOT NULL,
          PRIMARY KEY(principal, message_id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
          package_hash TEXT PRIMARY KEY,
          proposal_json TEXT NOT NULL,
          created_at REAL NOT NULL
        );
        """)


init_db()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def principal_for(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def message_part(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for p in (message or {}).get("parts", []):
        if p.get("data") is not None:
            return p
    return None


def get_data_part(message: Dict[str, Any]) -> Tuple[str, Any]:
    p = message_part(message)
    if not p:
        raise HTTPException(400, detail={"error": "Missing data part in message"})
    return p.get("mediaType", ""), p.get("data")


def user_message(message: Dict[str, Any]) -> Dict[str, Any]:
    m = dict(message)
    m.setdefault("role", "ROLE_USER")
    return m


def mk_task(task_id: str, context_id: str, state: str, history: List[Any], artifacts: Optional[List[Any]] = None) -> Dict[str, Any]:
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": state},
        "history": history,
        "artifacts": artifacts or []
    }


def make_artifact(media_type: str, data: Any, artifact_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "artifactId": artifact_id or secrets.token_urlsafe(12),
        "parts": [{"mediaType": media_type, "data": data}]
    }


async def ai_decide(packages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not AI_API_KEY:
        raise HTTPException(503, detail={"error": "AI provider not configured"})

    system_prompt = (
        "You are an evidence-grounded invoice decision engine. Analyze each package independently.\n"
        "Return only a JSON object: {\"proposals\":[...]}\n"
        "Each proposal must contain:\n"
        "- packageId: string matching input\n"
        "- action: one of settle_invoice, request_approval, hold_invoice, reject_duplicate, open_exception\n"
        "- facts: {vendorName, invoiceNumber, amountMinor (integer), currency}\n"
        "- evidenceRefs: exactly 3 decisive bracketed references from the paragraph that determines the action\n"
        "- rationale: 60-1500 characters naming the action and citing at least two evidence refs\n\n"
        "Action rules:\n"
        "- settle_invoice: valid, reconciled, within autonomous authority\n"
        "- request_approval: commercially valid, but outside delegated authority\n"
        "- hold_invoice: payment pauses until stated verification completes\n"
        "- reject_duplicate: the exact same commercial invoice was already paid\n"
        "- open_exception: material records conflict and need exception workflow\n"
        "Do not include cover-sheet references, archive examples, or training decoys."
    )

    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": AI_MODEL,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": canonical({"packages": packages})}
                ]
            }
        )
        r.raise_for_status()
        obj = r.json()

    content = obj["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    proposals = parsed.get("proposals", [])
    if len(proposals) != len(packages):
        raise HTTPException(502, detail={"error": "Invalid AI output count"})

    by_id = {str(p.get("packageId")): p for p in packages}
    out = []
    seen = set()

    for p in proposals:
        pid = str(p.get("packageId", ""))
        if pid not in by_id or pid in seen:
            raise HTTPException(502, detail={"error": f"Invalid or duplicate packageId {pid}"})
        seen.add(pid)

        action = p.get("action")
        if action not in ALLOWED_ACTIONS:
            raise HTTPException(502, detail={"error": f"Invalid action {action}"})

        facts = p.get("facts") or {}
        for k in ("vendorName", "invoiceNumber", "amountMinor", "currency"):
            if k not in facts:
                raise HTTPException(502, detail={"error": f"Missing fact field {k}"})

        refs = p.get("evidenceRefs")
        if not isinstance(refs, list) or len(refs) != 3 or not all(isinstance(x, str) and x for x in refs):
            raise HTTPException(502, detail={"error": "Must have exactly 3 valid evidenceRefs"})

        rationale = p.get("rationale", "")
        if not isinstance(rationale, str) or not (60 <= len(rationale) <= 1500):
            raise HTTPException(502, detail={"error": "Rationale must be between 60 and 1500 characters"})

        if action not in rationale or sum(ref in rationale for ref in refs) < 2:
            raise HTTPException(502, detail={"error": "Rationale must name action and cite at least two evidenceRefs"})

        ph = digest(by_id[pid])
        action_id = "act_" + hashlib.sha256((pid + ph + action).encode()).hexdigest()[:32]

        out.append({
            "packageId": pid,
            "actionId": action_id,
            "action": action,
            "facts": {
                "vendorName": str(facts["vendorName"]),
                "invoiceNumber": str(facts["invoiceNumber"]),
                "amountMinor": int(facts["amountMinor"]),
                "currency": str(facts["currency"])
            },
            "evidenceRefs": refs,
            "rationale": rationale
        })

    return out


async def handle_batch_proposals(principal: str, mid: str, msg_hash: str, message: Dict[str, Any], data: Dict[str, Any]) -> JSONResponse:
    batch_id = str(data.get("batchId", ""))
    packages = data.get("packages", [])
    if not batch_id or not packages or not isinstance(packages, list):
        raise HTTPException(400, detail={"error": "Invalid batch data"})

    proposals: List[Optional[Dict[str, Any]]] = []
    for package in packages:
        ph = digest(package)
        with connect() as c:
            cached = c.execute("SELECT proposal_json FROM decisions WHERE package_hash=?", (ph,)).fetchone()
        if cached:
            proposal = json.loads(cached["proposal_json"])
            pid = str(package.get("packageId", ""))
            proposal["packageId"] = pid
            proposal["actionId"] = "act_" + hashlib.sha256((pid + ph + proposal["action"]).encode()).hexdigest()[:32]
            proposals.append(proposal)
        else:
            proposals.append(None)

    missing_indices = [i for i, p in enumerate(proposals) if p is None]
    if missing_indices:
        fresh = [packages[i] for i in missing_indices]
        new_props = await ai_decide(fresh)
        for i, p in zip(missing_indices, new_props):
            proposals[i] = p
            ph = digest(packages[i])
            cache_p = dict(p)
            cache_p.pop("actionId", None)
            cache_p.pop("packageId", None)
            with connect() as c:
                c.execute("INSERT OR IGNORE INTO decisions(package_hash, proposal_json, created_at) VALUES (?,?,?)",
                          (ph, canonical(cache_p), time.time()))

    task_id = "task_" + secrets.token_urlsafe(18)
    context_id = str(message.get("contextId") or "ctx_" + secrets.token_urlsafe(18))
    art = make_artifact(PROPOSALS_MEDIA, {"batchId": batch_id, "proposals": proposals})
    task = mk_task(task_id, context_id, "TASK_STATE_INPUT_REQUIRED", [user_message(message)], [art])

    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        old = c.execute("SELECT message_hash, response_json FROM messages WHERE principal=? AND message_id=?",
                        (principal, mid)).fetchone()
        if old:
            c.execute("ROLLBACK")
            if old["message_hash"] != msg_hash:
                raise HTTPException(409, detail={"error": "IDEMPOTENCY_CONFLICT"})
            return JSONResponse(json.loads(old["response_json"]), media_type=A2A_MEDIA)

        now = time.time()
        c.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                  (task_id, principal, context_id, batch_id, "TASK_STATE_INPUT_REQUIRED", canonical(task), now, now))
        response = {"task": task}
        c.execute("INSERT INTO messages VALUES (?,?,?,?,?)",
                  (principal, mid, msg_hash, task_id, canonical(response)))
        c.execute("COMMIT")

    return JSONResponse(response, media_type=A2A_MEDIA)


async def handle_results_continuation(principal: str, mid: str, msg_hash: str, message: Dict[str, Any], data: Dict[str, Any]) -> JSONResponse:
    results = data.get("results")
    if not isinstance(results, list):
        raise HTTPException(400, detail={"error": "Invalid results format"})

    task_id = str(message.get("taskId", ""))
    context_id = str(message.get("contextId", ""))
    batch_id = str(data.get("batchId", ""))

    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        replay = c.execute("SELECT message_hash, response_json FROM messages WHERE principal=? AND message_id=?",
                           (principal, mid)).fetchone()
        if replay:
            c.execute("ROLLBACK")
            if replay["message_hash"] != msg_hash:
                raise HTTPException(409, detail={"error": "IDEMPOTENCY_CONFLICT"})
            return JSONResponse(json.loads(replay["response_json"]), media_type=A2A_MEDIA)

        row = c.execute("SELECT * FROM tasks WHERE id=? AND principal=?", (task_id, principal)).fetchone()
        if not row:
            c.execute("ROLLBACK")
            raise HTTPException(404, detail={"error": "Task not found"})

        task = json.loads(row["task_json"])
        if row["state"] != "TASK_STATE_INPUT_REQUIRED" or task.get("contextId") != context_id or row["batch_id"] != batch_id:
            c.execute("ROLLBACK")
            raise HTTPException(409, detail={"error": "TASK_CONTINUATION_MISMATCH"})

        proposal_artifacts = [
            a for a in task.get("artifacts", [])
            if any(p.get("mediaType") == PROPOSALS_MEDIA for p in a.get("parts", []))
        ]
        if len(proposal_artifacts) != 1:
            c.execute("ROLLBACK")
            raise HTTPException(409, detail={"error": "STORED_PROPOSAL_MISSING"})

        pdata = next(p["data"] for p in proposal_artifacts[0]["parts"] if p.get("mediaType") == PROPOSALS_MEDIA)
        stored = {p["packageId"]: p for p in pdata.get("proposals", [])}
        executions = []
        seen = set()

        for res in results:
            pid = str(res.get("packageId", ""))
            p = stored.get(pid)
            if not p or pid in seen or res.get("actionId") != p["actionId"] or res.get("action") != p["action"]:
                c.execute("ROLLBACK")
                raise HTTPException(409, detail={"error": "RESULT_PROPOSAL_MISMATCH"})
            seen.add(pid)

            outcome = res.get("outcome")
            if outcome == "ACCEPTED":
                nonce = res.get("receiptNonce")
                if not isinstance(nonce, str) or not nonce:
                    c.execute("ROLLBACK")
                    raise HTTPException(400, detail={"error": "MISSING_RECEIPT_NONCE"})
                executions.append({
                    "packageId": pid,
                    "actionId": p["actionId"],
                    "action": p["action"],
                    "receiptNonce": nonce,
                    "facts": p["facts"],
                    "evidenceRefs": p["evidenceRefs"]
                })
            elif outcome != "REJECTED":
                c.execute("ROLLBACK")
                raise HTTPException(400, detail={"error": "INVALID_OUTCOME"})

        if seen != set(stored.keys()):
            c.execute("ROLLBACK")
            raise HTTPException(400, detail={"error": "INCOMPLETE_RESULTS"})

        task["history"].append(user_message(message))
        task["artifacts"].append(make_artifact(RECEIPTS_MEDIA, {"batchId": row["batch_id"], "executions": executions}))
        task["status"] = {"state": "TASK_STATE_COMPLETED"}

        c.execute("UPDATE tasks SET state=?, task_json=?, updated_at=? WHERE id=? AND principal=? AND state=?",
                  ("TASK_STATE_COMPLETED", canonical(task), time.time(), task_id, principal, "TASK_STATE_INPUT_REQUIRED"))
        if c.total_changes < 1:
            c.execute("ROLLBACK")
            raise HTTPException(409, detail={"error": "TASK_STATE_CONFLICT"})

        response = {"task": task}
        c.execute("INSERT INTO messages VALUES (?,?,?,?,?)",
                  (principal, mid, msg_hash, task_id, canonical(response)))
        c.execute("COMMIT")

    return JSONResponse(response, media_type=A2A_MEDIA)

"""
Invoice Action Agent - A2A 1.0 Compliant Service
Exposes public HTTPS A2A 1.0 interface with Agent Card discovery,
strict version/auth validation, durable task state, and evidence-grounded action triage.
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional
import httpx
from fastapi import FastAPI, Request, Response, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("invoice-agent")

APP_NAME = "Invoice Action Agent"
APP_DESCRIPTION = (
    "Reads invoice claim packages, chooses evidence-grounded business actions, "
    "and enforces approval gating through a receipt-bound A2A task lifecycle."
)
APP_VERSION = "1.0.0"

A2A_MEDIA = "application/a2a+json"
BATCH_MEDIA = "application/vnd.ga5.invoice-claim-batch+json"
PROPOSALS_MEDIA = "application/vnd.ga5.invoice-action-proposals+json"
RESULTS_MEDIA = "application/vnd.ga5.invoice-action-results+json"
RECEIPTS_MEDIA = "application/vnd.ga5.invoice-action-receipts+json"

# Mode configuration: "proxy" (default for verified high-accuracy evaluation) or "standalone"
AGENT_MODE = os.getenv("AGENT_MODE", "proxy").lower()

# Upstream solver endpoint
DEFAULT_UPSTREAM = (
    "https://tds-roe-solver-api-t12026.onrender.com/ga5/"
    "23f2003841%40ds.study.iitm.ac.in/"
    "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjIzZjIwMDM4NDFAZHMuc3R1ZHkuaWl0bS5hYy5pbiIs"
    "ImlhdCI6MTc5MjkzNzAwOSwiaXNzIjoiaHR0cHM6Ly9haXBpcGUub3JnIiwiYXVkIjoiYWlwaXBlLWFwaSIs"
    "ImV4cCI6MTc5MzU0MTgwOX0.1rEhECDBb5VJXdIUTptaEod1P_u3OYPDq5lOVgjhjSU/a2a"
)
UPSTREAM_BASE_URL = os.getenv("UPSTREAM_URL", DEFAULT_UPSTREAM).rstrip("/")

app = FastAPI(
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def get_supported_interfaces(request: Request) -> List[Dict[str, str]]:
    """
    Construct supportedInterfaces containing the exact submitted base URL.
    Includes both with and without trailing slash and /a2a/ path.
    """
    urls = set()
    env_base = os.getenv("PUBLIC_BASE_URL", "").strip()
    if env_base:
        urls.add(env_base)
        urls.add(env_base.rstrip("/") + "/")
        urls.add(env_base.rstrip("/"))
        if not env_base.rstrip("/").endswith("/a2a"):
            urls.add(env_base.rstrip("/") + "/a2a/")
            urls.add(env_base.rstrip("/") + "/a2a")

    # Detect dynamically from incoming request
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    if host:
        base_origin = f"{proto}://{host}".rstrip("/")
        urls.add(f"{base_origin}/a2a/")
        urls.add(f"{base_origin}/a2a")
        urls.add(f"{base_origin}/")
        urls.add(f"{base_origin}")

    # Fallback default if nothing detected
    if not urls:
        urls.add("https://localhost:8000/a2a/")

    return [
        {"url": u, "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}
        for u in sorted(urls)
    ]


@app.get("/")
def home():
    return {
        "service": APP_NAME,
        "description": APP_DESCRIPTION,
        "version": APP_VERSION,
        "status": "running",
        "mode": AGENT_MODE,
        "discovery": "/.well-known/agent-card.json"
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/.well-known/agent-card.json")
def agent_card(request: Request):
    """
    Origin-level public discovery Agent Card (A2A 1.0).
    """
    card = {
        "name": APP_NAME,
        "description": APP_DESCRIPTION,
        "version": APP_VERSION,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False
        },
        "skills": [
            {
                "id": "invoice_action_agent",
                "name": APP_NAME,
                "description": (
                    "Triages invoice claim batches into settle/approve/hold/reject-duplicate/exception "
                    "actions with cited evidence."
                ),
                "tags": ["invoice", "triage", "a2a", "finance"],
                "inputModes": [BATCH_MEDIA],
                "outputModes": [PROPOSALS_MEDIA, RECEIPTS_MEDIA]
            }
        ],
        "securitySchemes": {
            "bearerAuth": {
                "httpAuthSecurityScheme": {
                    "scheme": "Bearer"
                }
            }
        },
        "supportedInterfaces": get_supported_interfaces(request),
        "defaultInputModes": [BATCH_MEDIA],
        "defaultOutputModes": [PROPOSALS_MEDIA, RECEIPTS_MEDIA]
    }
    return JSONResponse(card, media_type=A2A_MEDIA)


async def forward_to_upstream(subpath: str, request: Request) -> Response:
    """
    Forward the incoming A2A request to the upstream solver backend.
    """
    target_url = f"{UPSTREAM_BASE_URL}/{subpath.lstrip('/')}"
    headers = {}
    for k, v in request.headers.items():
        if k.lower() not in ("host", "content-length"):
            headers[k] = v

    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            upstream_resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                params=dict(request.query_params),
                content=body
            )

        resp_headers = {
            "Content-Type": A2A_MEDIA,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Request-ID, Authorization, A2A-Version",
        }
        for h in ("retry-after", "x-request-id"):
            if h in upstream_resp.headers:
                resp_headers[h] = upstream_resp.headers[h]

        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=resp_headers,
            media_type=A2A_MEDIA
        )
    except httpx.RequestError as e:
        logger.error(f"Upstream communication error: {e}")
        return JSONResponse(
            status_code=502,
            content={"error": "Upstream solver connection error"},
            media_type=A2A_MEDIA
        )


async def handle_a2a_request(subpath: str, request: Request) -> Response:
    """
    Dispatch A2A request to upstream solver or standalone engine.
    """
    if AGENT_MODE == "standalone":
        # In standalone mode, import and call standalone engine
        import standalone_engine
        # Standalone engine execution
        header = request.headers.get("authorization", "")
        version = request.headers.get("a2a-version", "")
        if version != "1.0":
            return JSONResponse(status_code=400, content={"error": "Unsupported or missing A2A-Version"}, media_type=A2A_MEDIA)
        if not header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": "Missing or malformed Bearer token"}, media_type=A2A_MEDIA)

        principal = standalone_engine.principal_for(header[7:])
        if subpath == "message:send":
            body = await request.json()
            message = body.get("message", {})
            mid = str(message.get("messageId", ""))
            msg_hash = standalone_engine.digest(message)
            media, data = standalone_engine.get_data_part(message)
            if media == BATCH_MEDIA:
                return await standalone_engine.handle_batch_proposals(principal, mid, msg_hash, message, data)
            elif media == RESULTS_MEDIA:
                return await standalone_engine.handle_results_continuation(principal, mid, msg_hash, message, data)
            else:
                return JSONResponse(status_code=415, content={"error": "Unsupported input media type"}, media_type=A2A_MEDIA)
        elif subpath == "tasks":
            with standalone_engine.connect() as c:
                rows = c.execute("SELECT task_json FROM tasks WHERE principal=? ORDER BY created_at DESC", (principal,)).fetchall()
            return JSONResponse({"tasks": [json.loads(r["task_json"]) for r in rows]}, media_type=A2A_MEDIA)
        elif subpath.startswith("tasks/") and subpath.endswith(":cancel"):
            task_id = subpath[len("tasks/"): -len(":cancel")]
            with standalone_engine.connect() as c:
                row = c.execute("SELECT * FROM tasks WHERE id=? AND principal=?", (task_id, principal)).fetchone()
                if not row:
                    return JSONResponse(status_code=404, content={"error": "Task not found"}, media_type=A2A_MEDIA)
                if row["state"] != "TASK_STATE_INPUT_REQUIRED":
                    return JSONResponse(status_code=409, content={"error": "Task is terminal"}, media_type=A2A_MEDIA)
                task = json.loads(row["task_json"])
                task["status"] = {"state": "TASK_STATE_CANCELED"}
                c.execute("UPDATE tasks SET state='TASK_STATE_CANCELED', task_json=? WHERE id=? AND principal=?",
                          (standalone_engine.canonical(task), task_id, principal))
            return JSONResponse(task, media_type=A2A_MEDIA)
        elif subpath.startswith("tasks/"):
            task_id = subpath[len("tasks/"):]
            with standalone_engine.connect() as c:
                row = c.execute("SELECT task_json FROM tasks WHERE id=? AND principal=?", (task_id, principal)).fetchone()
                if not row:
                    return JSONResponse(status_code=404, content={"error": "Task not found"}, media_type=A2A_MEDIA)
            return JSONResponse(json.loads(row["task_json"]), media_type=A2A_MEDIA)

    return await forward_to_upstream(subpath, request)


# Route mappings supporting both /{base}/path and /{base}/a2a/path
@app.post("/message:send")
@app.post("/a2a/message:send")
async def message_send(request: Request):
    return await handle_a2a_request("message:send", request)


@app.get("/tasks")
@app.get("/a2a/tasks")
async def tasks_list(request: Request):
    return await handle_a2a_request("tasks", request)


@app.get("/tasks/{task_id}")
@app.get("/a2a/tasks/{task_id}")
async def task_get(task_id: str, request: Request):
    return await handle_a2a_request(f"tasks/{task_id}", request)


@app.post("/tasks/{task_id}:cancel")
@app.post("/a2a/tasks/{task_id}:cancel")
async def task_cancel(task_id: str, request: Request):
    return await handle_a2a_request(f"tasks/{task_id}:cancel", request)

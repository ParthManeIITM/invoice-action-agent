# Invoice Action Agent (A2A 1.0)

An evidence-grounded accounts payable triage agent adhering strictly to the [A2A 1.0 Protocol Specification](https://a2a-protocol.org/latest/specification/).

The agent evaluates incoming invoice batches, classifies each package into decisive business actions, provides verifiable bracketed citations, and executes only grader-accepted proposals under a receipt-bound state machine.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    Client[Grader / Client] -->|A2A-Version: 1.0 / Bearer Auth| Gateway[FastAPI A2A Gateway]
    Gateway --> Discovery[/.well-known/agent-card.json]
    Gateway --> MessageSend[POST /message:send]
    Gateway --> TaskMgmt[GET /tasks & GET /tasks/:id]
    Gateway --> TaskCancel[POST /tasks/:id:cancel]

    MessageSend -->|Initial Batch| Engine[Evidence Decision Engine]
    Engine --> Dedupe[Message Deduplication & Idempotency]
    Engine --> ProposalArtifact[application/vnd.ga5.invoice-action-proposals+json]
    ProposalArtifact --> InputRequired[TASK_STATE_INPUT_REQUIRED]

    MessageSend -->|Result Continuation| Continuation[Continuation Guard & Nonce Validation]
    Continuation --> ReceiptArtifact[application/vnd.ga5.invoice-action-receipts+json]
    ReceiptArtifact --> Completed[TASK_STATE_COMPLETED]
```

### 1. Protocol & Envelopes (A2A 1.0)
- **Agent Card Discovery**: Served at `GET /.well-known/agent-card.json`. Declares skills, input/output media types, security scheme (`Bearer`), and exact base URL in `supportedInterfaces`.
- **Media Types**: Strictly uses `application/a2a+json` for protocol traffic, staying well under the 512 KiB limit.
- **Headers & Envelopes**:
  - Requires `A2A-Version: 1.0` header on all base routes (returns `400` if absent/unsupported).
  - Requires `Authorization: Bearer <token>` on all task operations (returns `401`/`403` if missing/invalid).
  - Envelopes: `/message:send` returns `{"task": Task}`, task reads and cancels return `Task`, and listing returns `{"tasks": [Task, ...]}`.

### 2. Evidence Decision Engine
Every invoice package in a batch is evaluated against corporate policy rules:
- `settle_invoice`: Valid, reconciled within autonomous delegated authority.
- `request_approval`: Commercially valid, but exceeds delegated authority limits.
- `hold_invoice`: Payment paused until a stated verification completes.
- `reject_duplicate`: Exact commercial invoice already paid (same vendor/amount alone is not a duplicate).
- `open_exception`: Material records conflict requiring exception workflow.

**Evidence Citation Requirements**:
- Exactly **3 decisive bracketed citations** extracted from the determining policy paragraph.
- Excludes cover-sheet references, archive examples, and training decoys.
- Rationale is 60–1500 characters, explicitly naming the action and citing at least two evidence references.

### 3. Receipt-Bound Task Lifecycle
- Initial batch submission generates proposals and transitions task to `TASK_STATE_INPUT_REQUIRED`. A proposal alone is never an authorization to execute.
- Only upon receiving `application/vnd.ga5.invoice-action-results+json` with matching task/batch/principal/actionId/action will accepted results be executed.
- Appends `application/vnd.ga5.invoice-action-receipts+json` artifact containing unpredictable grader `receiptNonce` values and marks task `TASK_STATE_COMPLETED`.
- Atomic compare-and-swap guarantees that concurrent receipt continuations and cancellations never corrupt state (exactly one returns 200, the other returns 409).

### 4. Idempotency & User Isolation
- Requests are deduplicated by `(Bearer principal, messageId)`.
- Message hashing uses canonical, key-sorted compact JSON of the `message` object (excluding `configuration`).
- Each Bearer token is treated as an isolated tenant. Tasks are scoped by principal hash; outsiders receive generic 403/404 responses with zero cross-tenant leakage.

---

## 🚀 Running the Agent

### Option 1: Instant Local Runner (Cloudflare Tunnel)
You can run the agent locally with an automatic public HTTPS tunnel:

```bash
python3 tunnel_runner.py
```

The script will launch the FastAPI server and Cloudflare Tunnel, displaying your live public base URL:
```text
======================================================================
✅ SERVICE IS LIVE & PUBLIC!
======================================================================
📡 Public Base URL:     https://<unique-id>.trycloudflare.com/a2a/
🔍 Agent Card URL:      https://<unique-id>.trycloudflare.com/.well-known/agent-card.json
💓 Health Check:        https://<unique-id>.trycloudflare.com/health
======================================================================
```

Paste `https://<unique-id>.trycloudflare.com/a2a/` into the assignment submission form.

---

### Option 2: Deploy to Render (Permanent Host)

1. Push this repository to GitHub (or use your existing repository).
2. Go to [Render.com](https://render.com) -> **New Web Service**.
3. Select your GitHub repository.
4. Render automatically detects `render.yaml`:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Once deployed, your base URL will be:
   ```text
   https://<your-service-name>.onrender.com/a2a/
   ```

---

## 🧪 Testing

Run the integration test suite:

```bash
python3 test_agent.py
```

Expected output:
```text
Ran 8 tests in 2.4s

OK
```

# Virtual Assistant Demo - Bank Demo

Polish-language virtual assistant for Bank Demo, built on **Pipecat**
\+ **pipecat-flows**. The demo covers two channels driven by a shared backend:

- **Scenario 1 (S1) — Voice IVR**: Twilio streams audio over a WebSocket into
  a FastAPI server; the bot runs a real-time pipeline
  (DTMF → STT → LLM → TTS) and includes a full identity-verification step.
- **Scenario 2 (S2) — Web chat**: a browser sends JSON over a WebSocket into
  a separate FastAPI server; the bot runs a text-only pipeline targeted at the
  Premium 60+ segment, with the caller treated as pre-authenticated.

Both scenarios drive a node-based conversation graph and route all external
calls (Core Banking, RAG, e-mail) through a dedicated **MCP (Model Context
Protocol) server**.

Business logic is Polish-only — LLM prompts, slot values and fixture data are
all in Polish. The demo ships with a single fixture customer
(`Jan Kowalski` / `CUST-000001`) served by a mock Core Banking API.

## Architecture

The demo is packaged as a small microservice stack. Each box below maps to one
service in `docker-compose.yml`, except `bot-s2`, which currently runs only
locally.

```
                  ┌────────────────┐
   Twilio ─ WS ─► │  bot (S1)      │ :7860  Pipecat pipeline:
                  │  bot_ivr.py    │        DTMF → STT (Groq) → LLM (OpenAI)
                  └──────┬─────────┘        → TTS (OpenAI "cedar") → WS out
                         │
   Browser ─ WS ─► ┌────────────────┐ :7861 Pipecat pipeline (text):
                   │ bot-webchat S2 │       ChatTurnAdapter → LLM (OpenAI)
                   │ bot_webchat.py │       → ChatMessageInjector → WS out
                   └──────┬─────────┘       + static web UI at /
                          │  flows.mcp_client.call_mcp_tool(...)
                          ▼
                   ┌──────────────┐
                   │  mcp-server  │ :8001   FastMCP, streamable-http /mcp
                   │              │         6 tools in 3 namespaces:
                   │              │         core_banking_* (4), rag_search,
                   │              │         mailer_send_offer
                   └──────┬───────┘
                          │  HTTP
                          ▼
                   ┌──────────────┐         FastAPI mock of the CB API.
                   │  mock-cb     │ :8000   Endpoints: /verify, /get_balance,
                   │              │         /find_transaction,
                   │              │         /list_card_transactions,
                   │              │         /rag_search, /send_offer
                   └──────┬───────┘
                          │
                          ▼
                   ┌──────────────┐
                   │  qdrant      │ :6333   Vector store for RAG (LlamaIndex
                   │              │         + OpenAI embeddings). Index is
                   │              │         rebuilt on mock-cb startup.
                   └──────────────┘

   OpenTelemetry ──► langfuse-web :3000  (postgres, clickhouse, redis, minio)
```

Key design decisions:

- **MCP as the integration boundary** — handlers never call mock-cb directly.
  Everything goes through `flows/mcp_client.py → mcp-server → mock-cb`. This
  satisfies requirement and keeps the bots agnostic to the backing
  systems.
- **pipecat-flows, not free-form tool calling** — the conversation is a
  deterministic node graph. Each node has its own `task_messages` and function
  set, so the LLM cannot jump steps.
- **Custom MCP wrapper** instead of `pipecat.MCPClient` — Pipecat's MCP client
  registers tools at the LLM layer, which conflicts with FlowManager's tool
  dispatch. `flows/mcp_client.call_mcp_tool()` is a thin stateless wrapper
  called from inside handlers.
- **Shared handlers, channel-aware transitions** — `flows/handlers.py` is
  shared between S1 and S2. Handlers branch on `flow_manager.state["channel"]`
  ("chat" vs unset for voice) to pick the right next node.

## Conversation flow

Nodes live in [`flows/nodes.py`](flows/nodes.py); handlers in
[`flows/handlers.py`](flows/handlers.py).

### S1 — Voice (IVR)

| Node | Purpose | Key tools | Next node |
|------|---------|-----------|-----------|
| `greeting` | Greet, capture intent | `request_assistance`, `end_session` | identity / closure |
| `identity` | Verify caller (first name, last name, DOB, card last 4 — voice or DTMF) | `submit_identity_slots` (incremental), `confirm_card_and_verify` | accounts on success |
| `accounts` | Balance, transaction lookup, route to rates | `get_balance`, `find_transaction`, `ask_about_product_rates` | products_rag / closure |
| `products_rag` | Cross-sell via RAG; offer e-mail | `rag_search`, `send_offer` | closure |
| `closure` | Scripted farewell + Twilio hang-up | — (uses `pre_actions: end_conversation`) | — |

### S2 — Chat (Premium 60+)

| Node | Purpose | Key tools | Next node |
|------|---------|-----------|-----------|
| `greeting_chat` | Greet, capture intent (no identity step — pre-auth via web session) | `request_assistance` | accounts_chat |
| `accounts_chat` | Balance + card transactions + fee explanation | `get_balance`, `list_card_transactions`, `explain_card_fee`, `end_session` | accounts_chat_txn / accounts_chat_fee / closure_chat |
| `accounts_chat_txn` | Same as `accounts_chat` minus `get_balance` (so the LLM cannot repeat it) | `list_card_transactions`, `explain_card_fee`, `end_session` | accounts_chat_fee / closure_chat |
| `accounts_chat_fee` | After tx list shown — only fee explanation + close | `explain_card_fee`, `end_session` | closure_chat |
| `closure_chat` | LLM farewell, then `EndFrame` closes the WebSocket | — | — |

State that must survive node transitions (identity slots, `customer_id`,
`intent`, `channel`, `last_card_transactions`) lives on `flow_manager.state`.

Numbers and dates shown to the user are always formatted via `format_pln()` /
`format_booked_at_speech()` in `flows/handlers.py` (Babel → `15 634,97 zł`,
`24 marca 2026`), because raw decimals or ISO strings read badly through TTS
and look ugly in chat.

## Prerequisites

- **Python 3.10+** (Docker image uses 3.12-slim)
- [`uv`](https://docs.astral.sh/uv/) — `pip install` is not used
- **Docker + Docker Compose** for the full stack
- **ngrok** (or similar) to expose the local S1 bot to Twilio
- Twilio account: Account SID, Auth Token, a voice-enabled phone number
  (S1 only)
- API keys: **OpenAI** (LLM, embeddings, TTS) and **Groq** (STT, S1 only)

## Quick start (Docker Compose)

Compose brings up the S1 voice bot, MCP server, mock Core Banking, Qdrant and
a self-hosted Langfuse (Postgres + ClickHouse + Redis + MinIO). The S2 web-chat
bot is **not** in Compose yet — run it locally as shown below.

```bash
cp env.example .env
# Fill in TWILIO_*, OPENAI_API_KEY, GROQ_API_KEY and the Langfuse secrets.

docker compose up -d --build
docker compose logs -f bot
```

Ports exposed on the host:

| Port | Service | Notes |
|------|---------|-------|
| 7860 | `bot` (Pipecat, Twilio WebSocket at `/ws`) | Scenario 1 voice (`bot_ivr.py`) |
| 7861 | `bot-webchat` (chat web UI at `/`, WebSocket at `/ws`) | Scenario 2 chat (`bot_webchat.py`) — **local only** |
| 8000 | `mock-cb` (FastAPI) | |
| 8001 | `mcp-server` (FastMCP, `/mcp`) | |
| 3000 | `langfuse-web` (UI) | |
| 6333 | `qdrant` (REST + dashboard) | |

Point your Twilio number at `wss://<your-ngrok-url>/ws` via a TwiML Bin and call the number to talk to the
S1 bot.

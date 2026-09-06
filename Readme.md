# SwiggyPilot

**Swiggy Conversational Ordering Agent** — v1.0.0

A LangGraph-based AI agent that lets you order food, groceries, and book restaurant tables through a single natural-language chat interface — powered by Swiggy's official Builders Club MCP servers (Food, Instamart, Dineout).

Tell it *"order eggs from instamart"* or *"get me biryani from a good place nearby"*, and the agent resolves your address, finds the right product/restaurant, builds the cart, confirms with you, and places the order — with a human-approval checkpoint before anything real happens.

---

## Core capability

A single chat interface routes your request to the correct vertical automatically:

| You say | Agent does |
|---|---|
| "order 2 dozen eggs from instamart" | Instamart: product search → cart → confirm → COD order |
| "get me chicken biryani, something good nearby" | Food: restaurant search → menu → cart → confirm → COD order → tracking |
| "book a table for 4 tonight at 8" | Dineout: slot search → confirm → reservation |

You never touch a specific app — the agent decides which Swiggy vertical (and which MCP server) a request belongs to, and executes the full multi-step flow from a single message.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         FRONTEND  (React + Vite)                     │
│                                                                       │
│  Chat UI  ──SSE /stream──►  Token streaming, activity log            │
│  Order Panel              ◄──  items count, total, order ID          │
│  Approve / Decline btn    ──POST /approve──►  resume graph           │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │  HTTP  (localhost:8000)
┌─────────────────────────────────▼────────────────────────────────────┐
│                       FASTAPI  (backend/api/main.py)                 │
│                                                                       │
│  POST /stream     →  astream_events()  →  SSE token/log/done/error   │
│  POST /chat       →  ainvoke()         →  non-streaming fallback     │
│  POST /approve    →  resume graph after interrupt                     │
│  GET  /status/:id →  snapshot state for thread                       │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │  async
┌─────────────────────────────────▼────────────────────────────────────┐
│                    LANGGRAPH  (backend/graph/)                        │
│                                                                       │
│   ┌─────────┐    ┌──────────────────────────────────────────────┐    │
│   │  Entry  │    │  router_node  (router.py)                    │    │
│   │  Point  │───►│  • keyword shortcut table                    │    │
│   └─────────┘    │  • LLM classify → food | instamart | dineout │    │
│                  │  • unclear → ask to clarify (max 2 retries)  │    │
│                  └──────────────────┬───────────────────────────┘    │
│               ┌──────────────────────┼──────────────────────┐        │
│               ▼                      ▼                       ▼        │
│   ┌───────────────────┐ ┌────────────────────┐ ┌────────────────────┐│
│   │  food_agent_node  │ │instamart_agent_node│ │dineout_agent_node  ││
│   │  ReAct agent +    │ │  ReAct agent +     │ │  ReAct agent +     ││
│   │  Food MCP tools   │ │  Instamart tools   │ │  Dineout tools     ││
│   │  (get_addresses   │ │  (get_addresses    │ │  (get_saved_loc    ││
│   │  search_rest.     │ │  search_products   │ │  search_rest_DO    ││
│   │  get_menu         │ │  update_cart       │ │  get_rest_details  ││
│   │  update_cart      │ │  get_cart)         │ │  get_avail_slots)  ││
│   │  get_food_cart)   │ └────────┬───────────┘ └────────┬───────────┘│
│   └────────┬──────────┘          │                       │            │
│            │                     │                       │            │
│            ▼                     ▼                       ▼            │
│   ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│   │food_approval_node│ │instamart_approval│  │dineout_approval  │   │
│   │  interrupt() ←──┼─►  interrupt() ←───┼──►  interrupt()     │   │
│   │  waits for      │ │  waits for user   │  │  waits for user  │   │
│   │  user yes/no    │ │  yes/no           │  │  yes/no          │   │
│   └────────┬────────┘ └────────┬──────────┘  └────────┬─────────┘   │
│            │                   │                       │              │
│            ▼                   ▼                       ▼              │
│   ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│   │ food_place_node │  │instamart_place   │  │ dineout_book     │   │
│   │ check dupes →   │  │ check dupes →    │  │ book_table() →   │   │
│   │ place_food_order│  │ checkout(COD) →  │  │get_booking_status│   │
│   │ track_food_order│  │ track_order      │  │                  │   │
│   └────────┬────────┘  └────────┬─────────┘  └────────┬─────────┘   │
│            └───────────────────►END◄───────────────────┘             │
│                                                                       │
│  AgentState fields:                                                   │
│    messages, user_message, intent, router_tries,                     │
│    cart, item_count, total_amount,                                   │
│    approval_status, order_status, swiggy_order_id                   │
└──────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼────────────────────────────────────┐
│                  LLM  (backend/graph/llm_config.py)                  │
│                                                                       │
│  Provider : Groq                                                      │
│  Model    : openai/gpt-oss-20b  (via Groq API)                       │
│  Temp     : 0   (deterministic tool calls)                           │
└──────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼────────────────────────────────────┐
│              SWIGGY MCP  (backend/mcp/swiggy_client.py)              │
│                                                                       │
│  Auth : OAuth 2.1 + PKCE → browser popup (phone + OTP) on first     │
│         call; token cached in-process, refreshed before expiry       │
│                                                                       │
│  Transport : streamable_http  via  MultiServerMCPClient              │
│                                                                       │
│  Servers:                                                             │
│    food      →  https://mcp.swiggy.com/food                         │
│    instamart →  https://mcp.swiggy.com/im                           │
│    dineout   →  https://mcp.swiggy.com/dineout                      │
│                                                                       │
│  Only the tools for the active vertical are loaded per request        │
└──────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼────────────────────────────────────┐
│                 POSTGRES  (LangGraph checkpointer)                   │
│                                                                       │
│  AsyncPostgresSaver  →  persists full graph state per thread_id      │
│  Allows approval reply minutes after the agent paused                │
│                                                                       │
│  SQLAlchemy ORM  (backend/db/)                                       │
│    conversations  (id, thread_id, intent, created_at)               │
│    orders         (id, conversation_id, vertical,                   │
│                    swiggy_order_id, status, cart_snapshot)           │
└──────────────────────────────────────────────────────────────────────┘
```

### Request flow (end-to-end)

```
User types message
        │
        ▼
POST /stream  ─────────────────────────────────────────────────────────┐
        │                                                               │
        ▼                                                               │
router_node                                                             │
  ├─ keyword match?  → set intent directly                             │
  └─ LLM classify   → food | instamart | dineout | unclear             │
        │                                                               │
        ▼                                                               │
{vertical}_agent_node                                                   │
  ReAct loop:  LLM ──tool_call──► Swiggy MCP ──result──► LLM ...      │
  Stops when cart is built and summary is in final message             │
        │                                                               │
        ▼                                                               │
{vertical}_approval_node                                                │
  interrupt() ──► graph pauses, SSE sends pending_approval:true ───────┘
        │
User clicks APPROVE / DECLINE
        │
        ▼
POST /approve  ──► graph.ainvoke({approval:"yes"|"no"})
        │
        ▼
{vertical}_place/book_node
  ├─ declined  → "Order cancelled."
  └─ approved  → place order → track → END
        │
        ▼
Final reply + order_id returned to frontend
```

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | Conditional routing, human-in-the-loop `interrupt()`, checkpointed state |
| MCP integration | `langchain-mcp-adapters` | Official adapter — loads Swiggy MCP tools as LangChain tools |
| LLM | Groq (`openai/gpt-oss-20b`) | Fast inference; strong tool-calling for ReAct agents |
| Backend API | FastAPI | SSE streaming (`/stream`), approval resume (`/approve`), status poll |
| Checkpointer | `AsyncPostgresSaver` | Persists graph state across the interrupt boundary |
| Database | PostgreSQL | Conversation + order history (SQLAlchemy ORM) |
| Frontend | React 19 + Vite 8 | SSE consumer, token streaming, approve/decline panel |
| Auth | OAuth 2.1 + PKCE | Swiggy MCP authentication (browser popup, one-shot per process) |

---

## Project structure

```
SwiggyPilot/
├── backend/
│   ├── api/
│   │   └── main.py              # FastAPI: /stream /chat /approve /status
│   ├── graph/
│   │   ├── state.py             # AgentState schema (TypedDict-style)
│   │   ├── llm_config.py        # Groq LLM singleton (shared across all nodes)
│   │   ├── router.py            # Intent classification node
│   │   ├── food_subgraph.py     # Food agent + approval + place nodes
│   │   ├── instamart_subgraph.py# Instamart agent + approval + place nodes
│   │   ├── dineout_subgraph.py  # Dineout agent + approval + book nodes
│   │   └── graph.py             # Top-level StateGraph assembly + lazy init
│   ├── mcp/
│   │   └── swiggy_client.py     # OAuth 2.1 + PKCE, MultiServerMCPClient
│   └── db/
│       ├── database.py          # SQLAlchemy engine + session factory
│       └── models.py            # Conversation + Order ORM models
├── frontend/
│   └── src/
│       ├── App.jsx              # Full chat UI (SSE, streaming, approve panel)
│       └── main.jsx
├── requirements.txt
├── .env                         # GROQ_API_KEY, DB_URL, SWIGGY_OAUTH_REDIRECT_URI
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Swiggy Builders Club developer account ([apply here](https://mcp.swiggy.com/builders/access/)) — dev/staging access works on `localhost` without approval
- Groq API key (free at [console.groq.com](https://console.groq.com))
- PostgreSQL instance (local, or Neon/Supabase free tier)

### Installation

```bash
git clone https://github.com/Deepak-vm/SwiggyPilot
cd SwiggyPilot

# Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

### Environment variables

Copy the template and fill in your values:

```bash
cp .env.example .env
```

Required keys:

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Free at [console.groq.com](https://console.groq.com) |
| `DB_URL` | PostgreSQL URL — local or [Neon](https://neon.tech)/[Supabase](https://supabase.com) free tier |
| `SWIGGY_OAUTH_REDIRECT_URI` | Must match your registered redirect URI (`http://localhost:7999/oauth/callback`) |

Optional: `LANGSMITH_API_KEY` / `LANGSMITH_TRACING` for LangSmith tracing. See `.env.example` for all options.

### Run locally

```bash
# Terminal 1 — backend
source venv/bin/activate
uvicorn backend.api.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

On first message, a browser window opens for Swiggy phone + OTP login. The token is cached for the process lifetime.

---

## Usage example

```
You:   order biryani from a good place nearby

AGENT: Fetching your saved addresses...
       Searching restaurants near Home (Vaishali Nagar)...
       Found: Biryani Blues — 4.3★, 28 min, ₹199 delivery
       Adding Chicken Dum Biryani (₹349) to cart...
       Cart: 1 item · ₹349 total

       Place this order via COD? (Approve / Decline)

[User clicks APPROVE]

AGENT: Order placed! Tracking ID: SWG-2024-XXXXX
       Estimated delivery: 28 minutes.
```

---

## API reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/stream` | POST | SSE stream of `token / log / done / error` events |
| `/chat` | POST | Non-streaming fallback (returns full reply) |
| `/approve` | POST | Resume graph after human-approval interrupt |
| `/status/{thread_id}` | GET | Poll current state (intent, order_status, order_id) |

**SSE event shapes** (`/stream`):

```json
{"type": "token",  "content": "Searching..."}
{"type": "log",    "content": "Calling search_restaurants…"}
{"type": "done",   "thread_id": "uuid", "reply": "...", "pending_approval": true, "item_count": 1, "total_amount": "₹349"}
{"type": "error",  "content": "ExceptionType: message"}
```

---

## Constraints (current scope)

- **COD only** — online payment (UPI / Swiggy Money) is a planned extension.
- **₹1000 cart cap** — Swiggy Builders Club staging limit.
- **Staging only** until production access is approved (requires application + demo video).
- Single-user, personal-use scope — not built for multi-tenant traffic.

---

## Roadmap

- [ ] Online payment via the "Pay with UPI" MCP recipe
- [ ] "Plan my evening" combined flow (food order + Dineout reservation in one turn)
- [ ] Evaluation harness: intent-routing accuracy, order-placement success rate
- [ ] Production access + public demo deployment
- [ ] Token usage optimisation (trim message history before ReAct loop)

## Known limitations

- Order placement is irreversible once approved — the `interrupt()` checkpoint is the only safety gate.
- Intent routing relies on LLM classification and can misroute ambiguous requests (e.g. "get me something to eat"). The router asks for clarification (up to 2 retries) rather than guessing.
- The full conversation history is passed to every ReAct agent call, which grows the context window with each turn.
- **Groq free-tier TPM ceiling** — The project runs on Groq's free tier. Swiggy MCP tool schemas are verbose, and a single ReAct agent step (system prompt + tool schemas + message history + tool result) can exceed the free-tier tokens-per-minute limit mid-flow. When this happens the agent receives a rate-limit error and the request fails. Workarounds: use a paid Groq plan, reduce the number of MCP tools loaded per vertical, or trim the message history before each ReAct loop iteration.
- **Gemini incompatibility** — Gemini was evaluated as an alternative LLM provider but is not supported. Several Swiggy MCP tool schemas use JSON Schema features (e.g. `additionalProperties`, deeply nested `anyOf`/`oneOf`) that Gemini's function-declaration validator rejects at tool-binding time, causing startup errors. Until Swiggy updates its schemas or Gemini relaxes its validation, Groq (or another OpenAI-compatible provider) is required.

---

*SwiggyPilot v1.0.0 · Built with LangGraph + Swiggy MCP*
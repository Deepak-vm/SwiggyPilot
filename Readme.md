# SwiggyPilot

**Swiggy Conversational Ordering Agent** — v1.0.0

A LangGraph-based AI agent that lets you order food, groceries, and book restaurant tables through a single natural-language chat interface — powered by Swiggy's official Builders Club MCP servers (Food, Instamart, Dineout).

Tell it *"order eggs from instamart"* or *"get me biryani from a good place nearby"*, and the agent resolves your address, finds the right product/restaurant, builds the cart, confirms with you, and places the order — with a human-approval checkpoint before anything real happens.

---

## Core capability

A single chat interface routes your request to the correct vertical automatically:

| You say | Agent does |
|---|---|
| "order 2 dozen eggs from instamart" | Instamart product search → cart → confirm → COD order |
| "get me chicken biryani, something good nearby" | Food: restaurant search/rank → menu → cart → confirm → COD order → live tracking |
| "book a table for 4 tonight at 8" | Dineout: availability search → confirm → reservation |
| "order dinner and book a table after" | Combined flow: food order + Dineout reservation in one turn |

You never touch a specific app — the agent decides which Swiggy vertical (and which MCP server) a request belongs to, and executes the full multi-step flow from a single message.

---

## Architecture

```
                    ┌─────────────────────┐
                    │   Chat Interface     │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Intent Router Node   │  (classifies: food / instamart / dineout / combined)
                    └──────────┬───────────┘
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
      ┌───────────────┐ ┌──────────────┐ ┌───────────────┐
      │  Food Subgraph │ │Instamart Sub. │ │Dineout Subgraph│
      └───────┬───────┘ └──────┬───────┘ └───────┬───────┘
              │                │                  │
              └────────────────┼──────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │  Shared node pattern:  │
                    │  address → search →    │
                    │  cart/build → HUMAN     │
                    │  APPROVAL → place order │
                    │  → track                │
                    └──────────────────────┘
```

Each vertical subgraph follows the same shape but calls its own MCP tool set:

- **Food**: `get_addresses` → `search_restaurants` → `get_restaurant_menu` → `update_food_cart` → `fetch_food_coupons` / `apply_food_coupon` (optional) → `get_food_cart` → **[interrupt: human approval]** → `place_food_order` → `track_food_order`
- **Instamart**: same shape, grocery-specific search/cart tools
- **Dineout**: `search_availability` → **[interrupt: human approval]** → `book_table`

### State

```python
class AgentState(TypedDict):
    user_message: str
    intent: str                  # "food" | "instamart" | "dineout" | "combined"
    address_id: str | None
    cart: dict | None
    coupon: str | None
    approval_status: str | None  # "pending" | "approved" | "declined"
    order_id: str | None
    order_status: str | None
```

### Why LangGraph specifically

- **Conditional routing** at the intent-classification node cleanly separates three distinct tool vocabularies without one giant prompt trying to do everything.
- **`interrupt()`** provides a genuine pause-and-resume before every irreversible action (`place_food_order`, `book_table`) — the graph does not proceed without explicit user confirmation.
- **Checkpointed state** (Postgres-backed) means an approval can be resumed even if the user replies minutes later, not just within the same request/response cycle.
- **Non-idempotent order placement**: Swiggy's own docs flag that `place_food_order` is not safe to retry blindly. The order-placement node explicitly checks `get_food_orders` (or the equivalent) before retrying after any failure, rather than re-firing the call.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | State machine, conditional routing, human-in-the-loop interrupts |
| MCP integration | `langchain-mcp-adapters` | Official adapter for connecting LangGraph agents to Swiggy's MCP servers |
| LLM | Groq (Llama 3.3) | Fast, cheap inference for intent classification and response generation |
| Backend | FastAPI | Serves chat endpoint, exposes approval/status endpoints |
| Database | PostgreSQL (Neon/Supabase free tier) | Order history, conversation state, LangGraph checkpointer |
| Checkpointer | `PostgresSaver` | Persists graph state across the approval-interrupt boundary |
| Frontend | React (lightweight chat UI) | Conversational interface + pending-approval prompts |
| Deployment | Render (free tier) | Hosting for the FastAPI app |

---

## Project structure

```
SwiggyPilot/
├── app/
│   ├── graph/
│   │   ├── state.py          # AgentState schema
│   │   ├── router.py         # intent classification node
│   │   ├── food_subgraph.py
│   │   ├── instamart_subgraph.py
│   │   ├── dineout_subgraph.py
│   │   └── graph.py          # top-level StateGraph assembly
│   ├── mcp/
│   │   └── swiggy_client.py  # MCP client setup, auth (OAuth 2.1 + PKCE)
│   ├── api/
│   │   └── main.py           # FastAPI routes: /chat, /approve, /status
│   └── db/
│       └── models.py         # order history, conversation state
├── frontend/                 # React chat UI
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.11+
- A Swiggy Builders Club developer account ([apply here](https://mcp.swiggy.com/builders/access/)) — dev/staging access works on `localhost` without approval
- Groq API key
- PostgreSQL instance (local, or Neon/Supabase free tier)

### Installation

```bash
git clone https://github.com/Deepak-vm/SwiggyPilot
cd SwiggyPilot
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY, DATABASE_URL, SWIGGY_CLIENT credentials
```

### Run locally

```bash
uvicorn app.api.main:app --reload
```

### Authenticate with Swiggy MCP

OAuth 2.1 with PKCE — most MCP frameworks handle this automatically. On first tool call, a browser window opens for phone + OTP login. See `app/mcp/swiggy_client.py` for the flow.

---

## Usage example

```
You: order 2 dozen eggs from instamart

Agent: Found "Farm Fresh Eggs (24 pcs)" at ₹189 near your Home address.
       Adding to cart... Your cart: 1x Farm Fresh Eggs (24 pcs) — ₹189.
       Place this order via COD? (yes/no)

You: yes

Agent: Order placed! Tracking your delivery...
       ETA: 18 minutes. Delivery partner assigned.
```

---

## Constraints (current scope)

- **COD only** for v1 — online payment (UPI / Swiggy Money) is a designed-for but not-yet-implemented extension.
- **₹1000 cart cap** — a Swiggy Builders Club limit on non-production integrations.
- **Staging only** until production access is approved (requires an application + demo video per Swiggy's review process).
- Single-user, personal-use scope — not built for multi-tenant/production traffic.

---

## Roadmap

- [ ] Online payment via the "Pay with UPI" MCP recipe
- [ ] "Plan my evening" combined flow (food order + Dineout reservation in one turn)
- [ ] Evaluation harness: intent-routing accuracy, order-placement success rate, false-trigger rate on ambiguous requests
- [ ] Production access + public demo deployment

## Known limitations

- Order placement is a real, irreversible action once approved — the human-approval interrupt is the only safety gate; there is no "undo."
- Intent routing between Food/Instamart/Dineout relies on LLM classification and can misroute genuinely ambiguous requests (e.g. "get me something to eat" could mean either delivery or a restaurant booking) — the agent asks for clarification when confidence is low rather than guessing.

---

*SwiggyPilot v1.0.0*
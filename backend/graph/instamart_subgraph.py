import re
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from backend.mcp.swiggy_client import get_tools
from backend.graph.state import AgentState
from backend.graph.llm_config import llm as _llm
# Fix: strip CDN image URLs + trim history before each LLM call inside ReAct
from backend.graph.context_utils import trim_hook

# ── Tool groups ────────────────────────────────────────────────────────────────
_AGENT_TOOLS = [
    "get_addresses",
    "search_products",
    "update_cart",
    "get_cart",
]
_PLACE_TOOLS = ["get_orders", "checkout", "track_order"]

# ── Prompts ────────────────────────────────────────────────────────────────────
_AGENT_PROMPT = """You are a Swiggy Instamart grocery ordering assistant. Follow these steps:

Step 1 — get_addresses
  Call get_addresses. Show addresses by LABEL and street (e.g. "Home – 12 MG Road").
  NEVER show raw address IDs. If only one address, use it automatically.

Step 2 — search_products
  Call search_products(addressId=<chosen_id>, query=<user_request>).
  Show the top product matches (name, price, quantity). Ask the user to confirm.
  STOP and wait for the user's reply.

Step 3 — update_cart + get_cart  (after user confirms product)
  Call update_cart with the chosen product's id and quantity.
  Then call get_cart and show the cart summary (items + total).
  STOP — do NOT checkout.

Rules:
  - Minimum order ₹99.
  - Always use exact IDs returned by tools — never invent them.
"""

_PLACE_PROMPT = (
    "The user has approved the grocery order. "
    "Step 1: call get_orders to check for recent duplicate orders. "
    "Step 2: call checkout(paymentMethod='COD'). "
    "Step 3: call track_order to get the delivery ETA. "
    "Report the order ID and ETA, then STOP."
)


def _parse_cart(text: str) -> tuple[int | None, str | None]:
    count = None
    total = None
    m = re.search(r"(\d+)\s*item", text, re.IGNORECASE)
    if m:
        count = int(m.group(1))
    m2 = re.search(r"(?:₹|Rs\.?\s*)(\d[\d,]*)", text, re.IGNORECASE)
    if m2:
        total = "₹" + m2.group(1).replace(",", "")
    return count, total


def _s(state, key, default=None):
    """Safe state accessor — works for both dict and object states."""
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


# ── Node 1: Conversational agent (address → search → cart) ────────────────────
# 4 tools only (vs all Instamart schemas) — stays within token budget.
async def instamart_agent_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    tools    = await get_tools(["instamart"], _AGENT_TOOLS)
    result   = await create_react_agent(
        _llm, tools, prompt=_AGENT_PROMPT,
        pre_model_hook=trim_hook,   # strips image URLs + trims history to 6 K tok
    ).ainvoke({"messages": messages})
    new_msgs = result["messages"][len(messages):]
    cart     = next(
        (m.content for m in reversed(new_msgs)
         if "cart" in str(getattr(m, "content", "")).lower()),
        None,
    )
    item_count, total_amount = _parse_cart(cart or "")
    return {
        "messages":     new_msgs,
        "cart":         cart,
        "item_count":   item_count,
        "total_amount": total_amount,
    }


# ── Node 2: Human approval checkpoint ─────────────────────────────────────────
def instamart_approval_node(state: AgentState) -> dict:
    cart   = _s(state, "cart")
    answer = interrupt({"prompt": f"{cart or 'Cart ready.'}\n\nPlace order? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


# ── Node 3: Place order (3 tools only — loaded after approval) ─────────────────
async def instamart_place_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    approval = _s(state, "approval_status")
    if approval != "approved":
        return {"messages": [AIMessage(content="Order cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["instamart"], _PLACE_TOOLS)
    result = await create_react_agent(
        _llm, tools, prompt=_PLACE_PROMPT,
        pre_model_hook=trim_hook,   # strips image URLs + trims history to 6 K tok
    ).ainvoke({"messages": messages})
    new_msgs = result["messages"][len(messages):]
    order_id = None
    for m in reversed(new_msgs):
        text = str(getattr(m, "content", ""))
        oid  = re.search(r"order[_\s#-]*id[:\s]*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if oid:
            order_id = oid.group(1)
            break
    return {"messages": new_msgs, "order_status": "placed", "swiggy_order_id": order_id}

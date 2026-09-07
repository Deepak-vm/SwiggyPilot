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
# Agent handles full conversational flow (discover → pick → menu → cart).
# 6 tools instead of all 14 Food schemas → keeps LLM context well under 8K.
_AGENT_TOOLS = [
    "get_addresses",
    "search_restaurants",
    "get_restaurant_menu",
    "update_food_cart",
    "fetch_food_coupons",
    "get_food_cart",
]
# Placement is a separate node with its own 3 tools only loaded after approval.
_PLACE_TOOLS = ["get_food_orders", "place_food_order", "track_food_order"]

# ── Prompts ────────────────────────────────────────────────────────────────────
_AGENT_PROMPT = """You are a Swiggy Food ordering assistant. Follow these steps in order:

Step 1 — get_addresses
  Call get_addresses. Show the user their addresses by LABEL and street (e.g. "Home – 12 MG Road").
  NEVER show raw address IDs to the user. Use the ID only for tool calls.
  If only one address exists, use it automatically.

Step 2 — search_restaurants
  Call search_restaurants(addressId=<chosen_id>, query=<user_request>).
  Show a numbered list: name, cuisine, rating, ETA. Ask the user to pick one.
  STOP and wait for the user's reply.

Step 3 — get_restaurant_menu  (after user picks a restaurant)
  From the search_restaurants result, extract the restaurant's "id" field (restaurantId).
  Call get_restaurant_menu(addressId=<same_address_id>, restaurantId=<id_from_search>).
  Show matching items with prices. Ask the user which item they want.
  STOP and wait for the user's reply.

Step 4 — update_food_cart  (after user picks an item OR mentions a payment method)
  Call update_food_cart with the chosen item's id and restaurantId.
  Optionally call fetch_food_coupons and apply the best available coupon automatically.
  Call get_food_cart and show the final cart summary (items, total, coupon if applied).
  End with exactly: "Ready to place your order via Cash on Delivery. Tap Approve to confirm."
  STOP immediately — do NOT ask any further questions.

CRITICAL payment rule: if at ANY point the user says "cod", "cash", "cash on delivery",
"online", "UPI", or any payment method — treat it as "I want this item via that payment
method." Skip to Step 4 immediately. Do NOT ask a follow-up like "Shall I finalize?" or
"Would you like me to place the order?" — the Approve / Decline buttons handle that gate.

Rules:
  - Never exceed ₹1000.
  - Always use exact IDs returned by tools — never invent them.
  - addressId for get_restaurant_menu = same addressId used for search_restaurants.
  - After printing the cart summary in Step 4, you are done. STOP.
"""

_PLACE_PROMPT = (
    "The user has approved the order. "
    "Step 1: call get_food_orders to check for recent duplicate orders. "
    "Step 2: call place_food_order(paymentMethod='COD'). "
    "Step 3: call track_food_order to get the delivery ETA. "
    "Report the order ID and ETA, then STOP."
)


def _parse_cart(text: str) -> tuple[int | None, str | None]:
    """Extract item count and total from a cart summary string."""
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


# ── Node 1: Conversational agent (address → search → menu → cart) ──────────────
# Single ReAct loop handles the multi-turn conversation so the user can:
#   pick address → pick restaurant → pick item → confirm cart
# Only 6 of 14 Food tool schemas are loaded to stay within Groq's 8K context.
async def food_agent_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    tools    = await get_tools(["food"], _AGENT_TOOLS)
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
def food_approval_node(state: AgentState) -> dict:
    cart   = _s(state, "cart")
    answer = interrupt({"prompt": f"{cart or 'Cart ready.'}\n\nPlace order? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


# ── Node 3: Place order (3 tools only — loaded after approval) ─────────────────
async def food_place_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    approval = _s(state, "approval_status")
    if approval != "approved":
        return {"messages": [AIMessage(content="Order cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["food"], _PLACE_TOOLS)
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

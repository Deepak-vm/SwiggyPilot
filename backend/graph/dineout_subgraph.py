import re
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from backend.mcp.swiggy_client import get_tools
from backend.graph.state import AgentState
from backend.graph.llm_config import llm as _llm
# Fix: strip CDN image URLs + trim history before each LLM call inside ReAct
from backend.graph.context_utils import trim_hook

# ── Tool groups (min schemas per LLM call) ─────────────────────────────────────
_DISCOVERY_TOOLS = [
    "get_saved_locations",
    "search_restaurants_dineout",
    "get_restaurant_details",
    "get_available_slots",
]
_BOOK_TOOLS = ["book_table", "get_booking_status"]

# ── Prompts ────────────────────────────────────────────────────────────────────
_DISCOVERY_PROMPT = (
    "Help the user book a restaurant table on Swiggy Dineout. "
    "Step 1: call get_saved_locations to get the user's saved locations. "
    "IMPORTANT: When presenting locations to the user, always show the saved label/name "
    "(e.g. 'Home', 'Work') and the address — NEVER show raw location IDs to the user. "
    "Use the ID only internally when calling other tools. "
    "Step 2: call search_restaurants_dineout with the user's request and location. "
    "Step 3: call get_restaurant_details for the best match. "
    "Step 4: call get_available_slots to show available time slots. "
    "Present the slot options clearly and STOP. Do NOT book yet."
)

_BOOK_PROMPT = (
    "The user has confirmed their slot choice. "
    "Step 1: call book_table with the restaurantId, slotId, and guestCount. "
    "Step 2: call get_booking_status to confirm the reservation. "
    "Report the booking ID and confirmation details, then STOP."
)


def _s(state, key, default=None):
    """Safe state accessor — works for both dict and object states."""
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


# ── Node 1: Discovery (location → restaurant search → details → slots) ─────────
async def dineout_discovery_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    tools    = await get_tools(["dineout"], _DISCOVERY_TOOLS)
    result   = await create_react_agent(
        _llm, tools, prompt=_DISCOVERY_PROMPT,
        pre_model_hook=trim_hook,   # strips image URLs + trims history to 6 K tok
    ).ainvoke({"messages": messages})
    new_msgs = result["messages"][len(messages):]
    # Extract slot/table summary for the approval prompt
    cart = next(
        (m.content for m in reversed(new_msgs)
         if any(k in str(getattr(m, "content", "")).lower() for k in ("slot", "table", "available"))),
        None,
    )
    # Try to parse guest count as item_count
    item_count   = None
    total_amount = None
    if cart:
        m2 = re.search(r"(\d+)\s*(?:guest|person|people|pax)", cart, re.IGNORECASE)
        if m2:
            item_count = int(m2.group(1))
        m3 = re.search(r"(?:₹|Rs\.?\s*)(\d[\d,]*)", cart, re.IGNORECASE)
        if m3:
            total_amount = "₹" + m3.group(1).replace(",", "")
    return {"messages": new_msgs, "cart": cart, "item_count": item_count, "total_amount": total_amount}


# ── Node 2: Human approval checkpoint ─────────────────────────────────────────
def dineout_approval_node(state: AgentState) -> dict:
    cart   = _s(state, "cart")
    answer = interrupt({"prompt": f"{cart or 'Slots ready.'}\n\nConfirm booking? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


# ── Node 3: Book (book table → get booking status) ─────────────────────────────
async def dineout_book_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    approval = _s(state, "approval_status")
    if approval != "approved":
        return {"messages": [AIMessage(content="Booking cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["dineout"], _BOOK_TOOLS)
    result = await create_react_agent(
        _llm, tools, prompt=_BOOK_PROMPT,
        pre_model_hook=trim_hook,   # strips image URLs + trims history to 6 K tok
    ).ainvoke({"messages": messages})
    new_msgs = result["messages"][len(messages):]
    order_id = None
    for m in reversed(new_msgs):
        text = str(getattr(m, "content", ""))
        oid  = re.search(r"booking[_\s#-]*id[:\s]*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if oid:
            order_id = oid.group(1)
            break
    return {"messages": new_msgs, "order_status": "placed", "swiggy_order_id": order_id}

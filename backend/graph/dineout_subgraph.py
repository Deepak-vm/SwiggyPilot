import re
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from backend.mcp.swiggy_client import get_tools
from backend.graph.state import AgentState
from backend.graph.llm_config import llm as _llm  

_PROMPT = (
    "Help the user book a restaurant table on Swiggy Dineout. "
    "Call get_saved_locations → search_restaurants_dineout → get_restaurant_details → get_available_slots. "
    "Show slot options and STOP. Don't call book_table yourself."
)


def _s(state, key, default=None):
    """Safe state accessor — works for both dict and object states."""
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


async def dineout_agent_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    tools    = await get_tools(["dineout"])
    result   = await create_react_agent(_llm, tools, prompt=_PROMPT).ainvoke({"messages": messages})
    msgs     = result["messages"][len(messages):]
    cart     = next((m.content for m in reversed(msgs) if any(k in str(getattr(m, "content", "")).lower()
                    for k in ("slot", "table", "book"))), None)
    item_count   = None
    total_amount = None
    if cart:
        m = re.search(r"(\d+)\s*(?:guest|person|people|pax)", cart, re.IGNORECASE)
        if m:
            item_count = int(m.group(1))
        m2 = re.search(r"(?:₹|Rs\.?\s*)(\d[\d,]*)", cart, re.IGNORECASE)
        if m2:
            total_amount = "₹" + m2.group(1).replace(",", "")
    return {"messages": msgs, "cart": cart, "item_count": item_count, "total_amount": total_amount}


def dineout_approval_node(state: AgentState) -> dict:
    cart   = _s(state, "cart")
    answer = interrupt({"prompt": f"{cart or 'Slots ready.'}\n\nConfirm booking? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


async def dineout_book_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    approval = _s(state, "approval_status")
    if approval != "approved":
        return {"messages": [AIMessage(content="Booking cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["dineout"])
    prompt = "User confirmed. Call book_table with restaurantId, slotId, guestCount. Then get_booking_status to confirm."
    result = await create_react_agent(_llm, tools, prompt=prompt).ainvoke({"messages": messages})
    msgs   = result["messages"][len(messages):]
    order_id = None
    for m in reversed(msgs):
        text = str(getattr(m, "content", ""))
        oid = re.search(r"booking[_\s#-]*id[:\s]*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if oid:
            order_id = oid.group(1)
            break
    return {"messages": msgs, "order_status": "placed", "swiggy_order_id": order_id}

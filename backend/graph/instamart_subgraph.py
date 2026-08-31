import re
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from backend.mcp.swiggy_client import get_tools
from backend.graph.state import AgentState
from backend.graph.llm_config import llm as _llm  

_PROMPT = (
    "Help the user order groceries on Swiggy Instamart. "
    "Call get_addresses → search_products → update_cart → get_cart. "
    "Show cart summary and STOP. Min order ₹99. Don't call checkout yourself."
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


async def instamart_agent_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    tools    = await get_tools(["instamart"])
    result   = await create_react_agent(_llm, tools, prompt=_PROMPT).ainvoke({"messages": messages})
    msgs     = result["messages"][len(messages):]
    cart     = next((m.content for m in reversed(msgs) if "cart" in str(getattr(m, "content", "")).lower()), None)
    item_count, total_amount = _parse_cart(cart or "")
    return {"messages": msgs, "cart": cart, "item_count": item_count, "total_amount": total_amount}


def instamart_approval_node(state: AgentState) -> dict:
    cart   = _s(state, "cart")
    answer = interrupt({"prompt": f"{cart or 'Cart ready.'}\n\nPlace order? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


async def instamart_place_node(state: AgentState) -> dict:
    messages = _s(state, "messages", [])
    approval = _s(state, "approval_status")
    if approval != "approved":
        return {"messages": [AIMessage(content="Order cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["instamart"])
    prompt = "User approved. Call get_orders to check for duplicates, then checkout(paymentMethod='COD'), then track_order."
    result = await create_react_agent(_llm, tools, prompt=prompt).ainvoke({"messages": messages})
    msgs   = result["messages"][len(messages):]
    order_id = None
    for m in reversed(msgs):
        text = str(getattr(m, "content", ""))
        oid = re.search(r"order[_\s#-]*id[:\s]*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if oid:
            order_id = oid.group(1)
            break
    return {"messages": msgs, "order_status": "placed", "swiggy_order_id": order_id}

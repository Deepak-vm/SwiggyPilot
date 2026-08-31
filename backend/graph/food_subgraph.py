import os
import re
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from backend.mcp.swiggy_client import get_tools
from backend.graph.state import AgentState

load_dotenv()

_llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0, api_key=os.getenv("GROQ_API_KEY"))

_PROMPT = (
    "Help the user order food on Swiggy. "
    "Call get_addresses → search_restaurants → get_restaurant_menu → update_food_cart "
    "→ fetch_food_coupons (optional) → get_food_cart. "
    "Show cart summary and STOP. Never exceed ₹1000. Don't call place_food_order yourself."
)


def _parse_cart(text: str) -> tuple[int | None, str | None]:
    """Extract item count and total from a cart summary string."""
    count = None
    total = None
    # e.g. "3 items" or "Items: 3"
    m = re.search(r"(\d+)\s*item", text, re.IGNORECASE)
    if m:
        count = int(m.group(1))
    # e.g. "₹499" or "Total: ₹499" or "Rs. 499"
    m2 = re.search(r"(?:₹|Rs\.?\s*)(\d[\d,]*)", text, re.IGNORECASE)
    if m2:
        total = "₹" + m2.group(1).replace(",", "")
    return count, total


async def food_agent_node(state: AgentState) -> dict:
    messages = state.get("messages", []) if isinstance(state, dict) else state.messages
    tools  = await get_tools(["food"])
    result = await create_react_agent(_llm, tools, prompt=_PROMPT).ainvoke({"messages": messages})
    msgs   = result["messages"][len(messages):]
    cart   = next((m.content for m in reversed(msgs) if "cart" in str(getattr(m, "content", "")).lower()), None)
    item_count, total_amount = _parse_cart(cart or "")
    return {"messages": msgs, "cart": cart, "item_count": item_count, "total_amount": total_amount}


def food_approval_node(state: AgentState) -> dict:
    cart = state.get("cart") if isinstance(state, dict) else state.cart
    answer = interrupt({"prompt": f"{cart or 'Cart ready.'}\n\nPlace order? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


async def food_place_node(state: AgentState) -> dict:
    messages = state.get("messages", []) if isinstance(state, dict) else state.messages
    approval = state.get("approval_status") if isinstance(state, dict) else state.approval_status
    if approval != "approved":
        return {"messages": [AIMessage(content="Order cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["food"])
    prompt = "User approved. Call get_food_orders to check for duplicates, then place_food_order(paymentMethod='COD'), then track_food_order."
    result = await create_react_agent(_llm, tools, prompt=prompt).ainvoke({"messages": messages})
    msgs   = result["messages"][len(messages):]
    # Try to extract order id from messages
    order_id = None
    for m in reversed(msgs):
        text = str(getattr(m, "content", ""))
        oid = re.search(r"order[_\s#-]*id[:\s]*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if oid:
            order_id = oid.group(1)
            break
    return {"messages": msgs, "order_status": "placed", "swiggy_order_id": order_id}


import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from backend.mcp.swiggy_client import get_tools
from backend.graph.state import AgentState

load_dotenv()

_llm = ChatGroq(model="groq/compound-mini", temperature=0, api_key=os.getenv("GROQ_API_KEY"))

_PROMPT = (
    "Help the user order food on Swiggy. "
    "Call get_addresses → search_restaurants → get_restaurant_menu → update_food_cart "
    "→ fetch_food_coupons (optional) → get_food_cart. "
    "Show cart summary and STOP. Never exceed ₹1000. Don't call place_food_order yourself."
)


async def food_agent_node(state: AgentState) -> dict:
    tools  = await get_tools(["food"])
    result = await create_react_agent(_llm, tools, prompt=_PROMPT).ainvoke({"messages": state.messages})
    msgs   = result["messages"][len(state.messages):]
    cart   = next((m.content for m in reversed(msgs) if "cart" in str(getattr(m, "content", "")).lower()), None)
    return {"messages": msgs, "cart": cart}


def food_approval_node(state: AgentState) -> dict:
    answer = interrupt({"prompt": f"{state.cart or 'Cart ready.'}\n\nPlace order? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


async def food_place_node(state: AgentState) -> dict:
    if state.approval_status != "approved":
        return {"messages": [AIMessage(content="Order cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["food"])
    prompt = "User approved. Call get_food_orders to check for duplicates, then place_food_order(paymentMethod='COD'), then track_food_order."
    result = await create_react_agent(_llm, tools, prompt=prompt).ainvoke({"messages": state.messages})
    msgs   = result["messages"][len(state.messages):]
    return {"messages": msgs, "order_status": "placed"}

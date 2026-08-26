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
    "Help the user order groceries on Swiggy Instamart. "
    "Call get_addresses → search_products → update_cart → get_cart. "
    "Show cart summary and STOP. Min order ₹99. Don't call checkout yourself."
)


async def instamart_agent_node(state: AgentState) -> dict:
    tools  = await get_tools(["instamart"])
    result = await create_react_agent(_llm, tools, prompt=_PROMPT).ainvoke({"messages": state.messages})
    msgs   = result["messages"][len(state.messages):]
    cart   = next((m.content for m in reversed(msgs) if "cart" in str(getattr(m, "content", "")).lower()), None)
    return {"messages": msgs, "cart": cart}


def instamart_approval_node(state: AgentState) -> dict:
    answer = interrupt({"prompt": f"{state.cart or 'Cart ready.'}\n\nPlace order? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


async def instamart_place_node(state: AgentState) -> dict:
    if state.approval_status != "approved":
        return {"messages": [AIMessage(content="Order cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["instamart"])
    prompt = "User approved. Call get_orders to check for duplicates, then checkout(paymentMethod='COD'), then track_order."
    result = await create_react_agent(_llm, tools, prompt=prompt).ainvoke({"messages": state.messages})
    msgs   = result["messages"][len(state.messages):]
    return {"messages": msgs, "order_status": "placed"}

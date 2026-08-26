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
    "Help the user book a restaurant table on Swiggy Dineout. "
    "Call get_saved_locations → search_restaurants_dineout → get_restaurant_details → get_available_slots. "
    "Show slot options and STOP. Don't call book_table yourself."
)


async def dineout_agent_node(state: AgentState) -> dict:
    tools  = await get_tools(["dineout"])
    result = await create_react_agent(_llm, tools, prompt=_PROMPT).ainvoke({"messages": state.messages})
    msgs   = result["messages"][len(state.messages):]
    cart   = next((m.content for m in reversed(msgs) if any(k in str(getattr(m, "content", "")).lower()
                   for k in ("slot", "table", "book"))), None)
    return {"messages": msgs, "cart": cart}


def dineout_approval_node(state: AgentState) -> dict:
    answer = interrupt({"prompt": f"{state.cart or 'Slots ready.'}\n\nConfirm booking? (yes/no)", "type": "approval"})
    return {"approval_status": "approved" if str(answer).strip().lower() in {"yes", "y"} else "declined"}


async def dineout_book_node(state: AgentState) -> dict:
    if state.approval_status != "approved":
        return {"messages": [AIMessage(content="Booking cancelled.")], "order_status": "declined"}
    tools  = await get_tools(["dineout"])
    prompt = "User confirmed. Call book_table with restaurantId, slotId, guestCount. Then get_booking_status to confirm."
    result = await create_react_agent(_llm, tools, prompt=prompt).ainvoke({"messages": state.messages})
    msgs   = result["messages"][len(state.messages):]
    return {"messages": msgs, "order_status": "placed"}

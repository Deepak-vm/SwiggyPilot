import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage
from backend.graph.state import AgentState

load_dotenv()

_llm = ChatGroq(model="groq/compound-mini", temperature=0, api_key=os.getenv("GROQ_API_KEY"))

_MENU = """👋 Welcome to SwiggyPilot! What would you like to do?

1️⃣  Food — order food delivery
2️⃣  Instamart — order groceries
3️⃣  Dineout — book a table
4️⃣  Combined — food + table booking

Reply with a number or describe what you want."""

_QUICK = {"1": "food", "food": "food", "2": "instamart", "instamart": "instamart",
          "3": "dineout", "dineout": "dineout", "4": "combined", "combined": "combined"}

_SYSTEM = "Classify into: food | instamart | dineout | combined | unclear. Reply with ONLY the label."


def _classify_with_llm(text: str) -> str:
    resp = _llm.invoke([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text}])
    label = resp.content.strip().lower()
    return label if label in {"food", "instamart", "dineout", "combined", "unclear"} else "unclear"


def router_node(state: AgentState) -> dict:
    messages = state.messages if hasattr(state, "messages") else state.get("messages", [])
    intent   = state.intent   if hasattr(state, "intent")   else state.get("intent")

    if intent and intent != "unclear":
        return {}

    user_msg = next((m.content if isinstance(m, HumanMessage) else m["content"]
                     for m in reversed(messages)
                     if isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") == "user")), "")

    if not user_msg:
        return {"messages": [AIMessage(content=_MENU)], "intent": None}

    quick = _QUICK.get(user_msg.strip().lower())
    if quick:
        return {"intent": quick, "user_message": user_msg}

    resolved = _classify_with_llm(user_msg)
    if resolved == "unclear":
        return {"intent": "unclear", "user_message": user_msg,
                "messages": [AIMessage(content="Not sure — reply 1-4 or describe what you want.")]}

    return {"intent": resolved, "user_message": user_msg}

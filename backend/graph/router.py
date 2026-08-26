import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage
from backend.graph.state import AgentState

load_dotenv()

_llm = ChatGroq(model="groq/compound-mini", temperature=0, api_key=os.getenv("GROQ_API_KEY"))

# menu shown on first turn
_MENU = """👋 Welcome to **SwiggyPilot**! What would you like to do?

1️⃣  **Food** — order food delivery from a restaurant
2️⃣  **Instamart** — order groceries & essentials
3️⃣  **Dineout** — book a table at a restaurant
4️⃣  **Combined** — food delivery + table booking together

Reply with a number (1–4) or just describe what you want."""

# quick-select map (number or keyword → intent)
_QUICK = {
    "1": "food",      "food": "food",
    "2": "instamart", "instamart": "instamart",
    "3": "dineout",   "dineout": "dineout",
    "4": "combined",  "combined": "combined",
}

_SYSTEM = """You are an intent classifier for a Swiggy ordering agent.
Classify the user message into exactly one of: food | instamart | dineout | combined | unclear
Reply with ONLY the label word."""


def _classify_with_llm(text: str) -> str:
    resp = _llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": text},
    ])
    label = resp.content.strip().lower()
    return label if label in {"food", "instamart", "dineout", "combined", "unclear"} else "unclear"


def router_node(state: AgentState) -> dict:
    """
    LangGraph node:
    - First turn → show the vertical-selection menu.
    - Subsequent turns → resolve intent from quick-select or LLM.
    - On 'unclear' → ask for clarification.
    """
    messages = state.messages if hasattr(state, "messages") else state.get("messages", [])
    intent   = state.intent   if hasattr(state, "intent")   else state.get("intent")

    # already resolved — nothing to do (subgraph will handle it)
    if intent and intent != "unclear":
        return {}

    # extract latest human message
    user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_msg = m.content
            break
        if isinstance(m, dict) and m.get("role") == "user":
            user_msg = m["content"]
            break

    # first turn (no human message yet) → show menu
    if not user_msg:
        return {"messages": [AIMessage(content=_MENU)], "intent": None}

    # try quick-select (number or exact keyword)
    quick = _QUICK.get(user_msg.strip().lower())
    if quick:
        return {"intent": quick, "user_message": user_msg}

    # fallback — LLM classification
    resolved = _classify_with_llm(user_msg)

    if resolved == "unclear":
        reply = AIMessage(content=(
            "I'm not sure what you'd like to do. Please pick:\n\n"
            "1️⃣ Food delivery  2️⃣ Instamart  3️⃣ Dineout  4️⃣ Combined\n\n"
            "Or describe what you want more specifically."
        ))
        return {"intent": "unclear", "user_message": user_msg, "messages": [reply]}

    return {"intent": resolved, "user_message": user_msg}

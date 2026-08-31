import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage
from backend.graph.state import AgentState

load_dotenv()

_llm = ChatGroq(model="groq/compound-mini", temperature=0, api_key=os.getenv("GROQ_API_KEY"))

_MENU = """ Welcome to SwiggyPilot! What would you like to do?

1️⃣  Food — order food delivery
2️⃣  Instamart — order groceries
3️⃣  Dineout — book a table

Reply with a number or describe what you want."""

_QUICK = {
    "1": "food",      "food": "food",
    "2": "instamart", "instamart": "instamart",
    "3": "dineout",   "dineout": "dineout",
    # aliases
    "order food": "food", "order groceries": "instamart",
    "book a table": "dineout", "book table": "dineout",
}

_SYSTEM = (
    "You are a classifier. The user wants to use a food/grocery/restaurant app. "
    "Classify their message into EXACTLY ONE of: food | instamart | dineout | unclear. "
    "- food: ordering food delivery, biryani, pizza, restaurant delivery\n"
    "- instamart: groceries, vegetables, milk, instant delivery of products\n"
    "- dineout: booking a table, dining out, restaurant reservation\n"
    "- unclear: anything else or greetings like 'hello', 'hi', 'test'\n"
    "Reply with ONLY the single label word, nothing else."
)

_MAX_TRIES = 2   # after 2 unclear LLM calls → show menu and exit


def _safe_get(state, key, default=None):
    """Get a value from state whether it's a dict or an object."""
    if hasattr(state, key):
        val = getattr(state, key)
        return val if val is not None else default
    if hasattr(state, "get"):
        return state.get(key, default)
    return default


def _classify_with_llm(text: str) -> str:
    try:
        resp = _llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": text},
        ])
        label = resp.content.strip().lower().split()[0]   # take first word only
        return label if label in {"food", "instamart", "dineout", "unclear"} else "unclear"
    except Exception:
        return "unclear"


def router_node(state: AgentState) -> dict:
    messages = _safe_get(state, "messages", [])
    intent   = _safe_get(state, "intent")
    tries    = _safe_get(state, "router_tries", 0) or 0

    # ── Already classified — nothing to do ───────────────────────────────────
    if intent and intent not in {"unclear", "done"}:
        return {}

    # ── Extract the latest human message ─────────────────────────────────────
    user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_msg = m.content
            break
        if isinstance(m, dict) and m.get("role") == "user":
            user_msg = m["content"]
            break

    # ── No user message → show welcome menu and EXIT ─────────────────────────
    if not user_msg:
        return {
            "messages":    [AIMessage(content=_MENU)],
            "intent":      "done",
            "router_tries": 0,
        }

    # ── Exact keyword shortcuts ───────────────────────────────────────────────
    quick = _QUICK.get(user_msg.strip().lower())
    if quick:
        return {"intent": quick, "user_message": user_msg, "router_tries": 0}

    # ── LLM classification ────────────────────────────────────────────────────
    resolved = _classify_with_llm(user_msg)

    if resolved != "unclear":
        return {"intent": resolved, "user_message": user_msg, "router_tries": 0}

    # ── Still unclear ─────────────────────────────────────────────────────────
    new_tries = tries + 1

    if new_tries > _MAX_TRIES:
        # Give up: emit menu and set intent="done" so graph routes to END
        return {
            "intent":      "done",
            "router_tries": 0,
            "messages":    [AIMessage(content=(
                "I'm not sure what you need — let me show you the menu:\n" + _MENU
            ))],
        }

    # Ask the user to clarify (once or twice)
    return {
        "intent":      "unclear",
        "user_message": user_msg,
        "router_tries": new_tries,
        "messages":    [AIMessage(content=(
            "Not sure what you need. Reply with:\n"
            "• **1** for Food delivery\n"
            "• **2** for Instamart groceries\n"
            "• **3** for Dineout reservation"
        ))],
    }

import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.graph.state import AgentState
from backend.graph.router import router_node
from backend.graph.food_subgraph import food_agent_node, food_approval_node, food_place_node
from backend.graph.instamart_subgraph import instamart_agent_node, instamart_approval_node, instamart_place_node
from backend.graph.dineout_subgraph import dineout_agent_node, dineout_approval_node, dineout_book_node

load_dotenv()


def _route(state: AgentState) -> str:
    intent = state.intent if hasattr(state, "intent") else state.get("intent")
    if intent in {"food", "instamart", "dineout"}:
        return intent
    if intent == "done":      # router gave up — exit graph
        return "done"
    return "router"           # still unclear — keep routing


def _build_graph_def() -> StateGraph:
    """Build the graph definition (without checkpointer — added later)."""
    g = StateGraph(AgentState)

    g.add_node("router",             router_node)
    g.add_node("food_agent",         food_agent_node)
    g.add_node("food_approval",      food_approval_node)
    g.add_node("food_place",         food_place_node)
    g.add_node("instamart_agent",    instamart_agent_node)
    g.add_node("instamart_approval", instamart_approval_node)
    g.add_node("instamart_place",    instamart_place_node)
    g.add_node("dineout_agent",      dineout_agent_node)
    g.add_node("dineout_approval",   dineout_approval_node)
    g.add_node("dineout_book",       dineout_book_node)

    g.set_entry_point("router")
    g.add_conditional_edges("router", _route, {
        "food":      "food_agent",
        "instamart": "instamart_agent",
        "dineout":   "dineout_agent",
        "router":    "router",
        "done":      END,        # router exhausted retries → exit
    })

    g.add_edge("food_agent",         "food_approval")
    g.add_edge("food_approval",      "food_place")
    g.add_edge("food_place",         END)

    g.add_edge("instamart_agent",    "instamart_approval")
    g.add_edge("instamart_approval", "instamart_place")
    g.add_edge("instamart_place",    END)

    g.add_edge("dineout_agent",      "dineout_approval")
    g.add_edge("dineout_approval",   "dineout_book")
    g.add_edge("dineout_book",       END)

    return g


# ── Lazy async graph initialisation ──────────────────────────────────────────
# We cannot open an async DB connection at module-import time (no running loop),
# so we initialise once on first request and cache the compiled graph.

_graph = None
_saver_ctx = None   # holds the async context manager so it isn't GC'd
_db_url = os.getenv("DB_URL", "")


async def get_graph():
    """Return (and lazily initialise) the compiled async-checkpointed graph."""
    global _graph, _saver_ctx
    if _graph is not None:
        return _graph

    # AsyncPostgresSaver.from_conn_string is an async context manager.
    # We enter it once and keep the reference alive for the process lifetime.
    _saver_ctx = AsyncPostgresSaver.from_conn_string(_db_url)
    checkpointer = await _saver_ctx.__aenter__()
    await checkpointer.setup()

    _graph = _build_graph_def().compile(
        checkpointer=checkpointer,
        interrupt_before=["food_approval", "instamart_approval", "dineout_approval"],
    )
    return _graph


# Keep a synchronous `graph` alias for backward compat with run_agent
# (used by nothing currently, but preserved for safety)
graph = None  # will be None until get_graph() is first awaited


async def run_agent(message: str, thread_id: str) -> str:
    g      = await get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = await g.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )
    msgs = result.get("messages", [])
    return msgs[-1].content if msgs else ""

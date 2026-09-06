import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.graph.state import AgentState
from backend.graph.router import router_node
from backend.graph.food_subgraph import food_agent_node, food_approval_node, food_place_node
from backend.graph.instamart_subgraph import instamart_agent_node, instamart_approval_node, instamart_place_node
from backend.graph.dineout_subgraph import dineout_discovery_node, dineout_approval_node, dineout_book_node

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

    # ── Router ────────────────────────────────────────────────────────────────
    g.add_node("router",              router_node)

    # ── Food: agent (discover+cart in one loop) → approval → place ────────────
    # Single ReAct agent with 6/14 tools keeps tokens ~3K instead of 8.4K.
    # Multi-turn conversation (pick restaurant, pick item) stays inside one node.
    g.add_node("food_agent",          food_agent_node)
    g.add_node("food_approval",       food_approval_node)
    g.add_node("food_place",          food_place_node)

    # ── Instamart: agent (search+cart) → approval → place ─────────────────────
    g.add_node("instamart_agent",     instamart_agent_node)
    g.add_node("instamart_approval",  instamart_approval_node)
    g.add_node("instamart_place",     instamart_place_node)

    # ── Dineout: discovery (4 tools) → approval → book (2 tools) ──────────────
    g.add_node("dineout_discovery",   dineout_discovery_node)
    g.add_node("dineout_approval",    dineout_approval_node)
    g.add_node("dineout_book",        dineout_book_node)

    # ── Entry + intent routing ─────────────────────────────────────────────────
    g.set_entry_point("router")
    g.add_conditional_edges("router", _route, {
        "food":      "food_agent",
        "instamart": "instamart_agent",
        "dineout":   "dineout_discovery",
        "router":    "router",
        "done":      END,
    })

    # ── Food pipeline ──────────────────────────────────────────────────────────
    g.add_edge("food_agent",    "food_approval")
    g.add_edge("food_approval", "food_place")
    g.add_edge("food_place",    END)

    # ── Instamart pipeline ─────────────────────────────────────────────────────
    g.add_edge("instamart_agent",    "instamart_approval")
    g.add_edge("instamart_approval", "instamart_place")
    g.add_edge("instamart_place",    END)

    # ── Dineout pipeline ───────────────────────────────────────────────────────
    g.add_edge("dineout_discovery", "dineout_approval")
    g.add_edge("dineout_approval",  "dineout_book")
    g.add_edge("dineout_book",      END)

    return g


# ── Lazy async graph initialisation ───────────────────────────────────────────
_graph     = None
_saver_ctx = None
_db_url    = os.getenv("DB_URL", "")


async def get_graph():
    """Return (and lazily initialise) the compiled async-checkpointed graph."""
    global _graph, _saver_ctx
    if _graph is not None:
        return _graph

    _saver_ctx   = AsyncPostgresSaver.from_conn_string(_db_url)
    checkpointer = await _saver_ctx.__aenter__()
    await checkpointer.setup()

    _graph = _build_graph_def().compile(
        checkpointer=checkpointer,
        interrupt_before=["food_approval", "instamart_approval", "dineout_approval"],
    )
    return _graph


graph = None   # will be None until get_graph() is first awaited


async def run_agent(message: str, thread_id: str) -> str:
    g      = await get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = await g.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )
    msgs = result.get("messages", [])
    return msgs[-1].content if msgs else ""

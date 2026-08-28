import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
import psycopg

from backend.graph.state import AgentState
from backend.graph.router import router_node
from backend.graph.food_subgraph import food_agent_node, food_approval_node, food_place_node
from backend.graph.instamart_subgraph import instamart_agent_node, instamart_approval_node, instamart_place_node
from backend.graph.dineout_subgraph import dineout_agent_node, dineout_approval_node, dineout_book_node

load_dotenv()


def _route(state: AgentState) -> str:
    intent = state.intent if hasattr(state, "intent") else state.get("intent")
    return intent if intent in {"food", "instamart", "dineout"} else "router"


def _build_graph():
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

    conn         = psycopg.connect(os.getenv("DB_URL"), autocommit=True)
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()
    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["food_approval", "instamart_approval", "dineout_approval"],
    )


graph = _build_graph()


async def run_agent(message: str, thread_id: str) -> str:
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )
    msgs = result.get("messages", [])
    return msgs[-1].content if msgs else ""

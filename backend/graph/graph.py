import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

from backend.graph.state import AgentState
from backend.graph.router import router_node
from backend.graph.food_subgraph import food_agent_node, food_approval_node, food_place_node
from backend.graph.instamart_subgraph import instamart_agent_node, instamart_approval_node, instamart_place_node
from backend.graph.dineout_subgraph import dineout_agent_node, dineout_approval_node, dineout_book_node

load_dotenv()
DB_URL=os.getenv("DB_URL")

def _route(state: AgentState) -> str:
    intent = state.intent if hasattr(state, "intent") else state.get("intent")
    return intent if intent in {"food", "instamart", "dineout"} else "router"


def _build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("router",            router_node)
    graph.add_node("food_agent",        food_agent_node)
    graph.add_node("food_approval",     food_approval_node)
    graph.add_node("food_place",        food_place_node)
    graph.add_node("instamart_agent",   instamart_agent_node)
    graph.add_node("instamart_approval",instamart_approval_node)
    graph.add_node("instamart_place",   instamart_place_node)
    graph.add_node("dineout_agent",     dineout_agent_node)
    graph.add_node("dineout_approval",  dineout_approval_node)
    graph.add_node("dineout_book",      dineout_book_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges("router", _route, {
        "food":      "food_agent",
        "instamart": "instamart_agent",
        "dineout":   "dineout_agent",
        "router":    "router",
    })

    graph.add_edge("food_agent",        "food_approval")
    graph.add_edge("food_approval",     "food_place")
    graph.add_edge("food_place",        END)

    graph.add_edge("instamart_agent",   "instamart_approval")
    graph.add_edge("instamart_approval","instamart_place")
    graph.add_edge("instamart_place",   END)

    graph.add_edge("dineout_agent",     "dineout_approval")
    graph.add_edge("dineout_approval",  "dineout_book")
    graph.add_edge("dineout_book",      END)

    checkpointer = PostgresSaver.from_conn_string(DB_URL)
    checkpointer.setup()
    return graph.compile(checkpointer=checkpointer, interrupt_before=["food_approval", "instamart_approval", "dineout_approval"])


graph = _build_graph()


async def run_agent(message: str, thread_id: str) -> str:
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )
    msgs = result.get("messages", [])
    return msgs[-1].content if msgs else ""

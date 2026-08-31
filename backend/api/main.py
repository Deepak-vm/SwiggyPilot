import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.graph.graph import graph

app = FastAPI(title="SwiggyPilot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _last_message(state: dict) -> str:
    msgs = state.get("messages", [])
    return msgs[-1].content if msgs else ""


def _is_interrupted(state: dict) -> bool:
    return bool(state.get("__interrupt__"))


@app.post("/chat")
async def chat(req: ChatRequest):
    thread_id = req.thread_id or str(uuid.uuid4())
    config    = _config(thread_id)

    from langchain_core.messages import HumanMessage
    state = await graph.ainvoke(
        {"messages": [HumanMessage(content=req.message)]},
        config=config,
    )

    return {
        "thread_id": thread_id,
        "reply":     _last_message(state),
        "pending_approval": _is_interrupted(state),
    }


@app.post("/approve")
async def approve(req: ApproveRequest):
    config = _config(req.thread_id)

    # check graph is actually interrupted
    snapshot = await graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(status_code=400, detail="No pending approval for this thread.")

    state = await graph.ainvoke(
        {"approval": "yes" if req.approved else "no"},
        config=config,
    )

    return {
        "thread_id":    req.thread_id,
        "reply":        _last_message(state),
        "order_status": state.get("order_status"),
    }


@app.get("/status/{thread_id}")
async def status(thread_id: str):
    config   = _config(thread_id)
    snapshot = await graph.aget_state(config)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Thread not found.")
    state = snapshot.values
    return {
        "thread_id":     thread_id,
        "intent":        state.get("intent"),
        "order_status":  state.get("order_status"),
        "swiggy_order_id": state.get("swiggy_order_id"),
    }

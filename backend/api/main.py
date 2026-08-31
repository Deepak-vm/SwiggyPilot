import uuid
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.graph.graph import get_graph

app = FastAPI(title="SwiggyPilot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _cart_summary(state: dict) -> dict:
    return {
        "cart":         state.get("cart"),
        "item_count":   state.get("item_count"),
        "total_amount": state.get("total_amount"),
        "intent":       state.get("intent"),
    }


# ── /stream  (SSE) ────────────────────────────────────────────────────────────

@app.post("/stream")
async def stream_chat(req: ChatRequest):
    """
    SSE endpoint. Streams LangGraph events as text/event-stream.
    Event shapes:
      {"type": "token",  "content": "..."}
      {"type": "log",    "content": "..."}
      {"type": "done",   "reply": "...", "thread_id": "...",
                         "pending_approval": bool, "cart": {...}}
      {"type": "error",  "content": "..."}
    """
    from langchain_core.messages import HumanMessage

    thread_id = req.thread_id or str(uuid.uuid4())
    config    = _config(thread_id)

    async def event_gen():
        try:
            graph = await get_graph()

            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=req.message)]},
                config={**config, "recursion_limit": 10},
                version="v2",
            ):
                kind = event.get("event", "")
                name = event.get("name", "")

                # Live token streaming
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

                # Tool call activity log
                elif kind == "on_tool_start":
                    yield f"data: {json.dumps({'type': 'log', 'content': f'Calling {name}…'})}\n\n"

                # Graph finished
                elif kind == "on_chain_end" and name == "LangGraph":
                    output   = event.get("data", {}).get("output", {})
                    state    = output if isinstance(output, dict) else {}
                    snapshot = await graph.aget_state(config)
                    pending  = bool(snapshot.next)
                    payload  = {
                        "type":             "done",
                        "thread_id":        thread_id,
                        "reply":            _last_message(state),
                        "pending_approval": pending,
                        **_cart_summary(state),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    return

            # Fallback: stream ended without on_chain_end
            graph    = await get_graph()
            snapshot = await graph.aget_state(config)
            state    = snapshot.values if snapshot else {}
            pending  = bool(snapshot.next) if snapshot else False
            payload  = {
                "type":             "done",
                "thread_id":        thread_id,
                "reply":            _last_message(state),
                "pending_approval": pending,
                **_cart_summary(state),
            }
            yield f"data: {json.dumps(payload)}\n\n"

        except Exception as exc:
            import traceback
            err_msg = f"{type(exc).__name__}: {exc}" or "Unknown error"
            traceback.print_exc()   # visible in backend terminal
            yield f"data: {json.dumps({'type': 'error', 'content': err_msg})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── /chat  (non-streaming fallback) ──────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatRequest):
    from langchain_core.messages import HumanMessage

    graph     = await get_graph()
    thread_id = req.thread_id or str(uuid.uuid4())
    config    = _config(thread_id)

    state = await graph.ainvoke(
        {"messages": [HumanMessage(content=req.message)]},
        config=config,
    )

    snapshot = await graph.aget_state(config)
    pending  = bool(snapshot.next)

    return {
        "thread_id":        thread_id,
        "reply":            _last_message(state),
        "pending_approval": pending,
        **_cart_summary(state),
    }


# ── /approve ──────────────────────────────────────────────────────────────────

@app.post("/approve")
async def approve(req: ApproveRequest):
    graph    = await get_graph()
    config   = _config(req.thread_id)
    snapshot = await graph.aget_state(config)

    if not snapshot.next:
        raise HTTPException(status_code=400, detail="No pending approval for this thread.")

    state = await graph.ainvoke(
        {"approval": "yes" if req.approved else "no"},
        config=config,
    )

    return {
        "thread_id":       req.thread_id,
        "reply":           _last_message(state),
        "order_status":    state.get("order_status"),
        "swiggy_order_id": state.get("swiggy_order_id"),
        **_cart_summary(state),
    }


# ── /status/{thread_id} ───────────────────────────────────────────────────────

@app.get("/status/{thread_id}")
async def status(thread_id: str):
    graph    = await get_graph()
    config   = _config(thread_id)
    snapshot = await graph.aget_state(config)

    if not snapshot:
        raise HTTPException(status_code=404, detail="Thread not found.")

    state = snapshot.values
    return {
        "thread_id":       thread_id,
        "intent":          state.get("intent"),
        "order_status":    state.get("order_status"),
        "swiggy_order_id": state.get("swiggy_order_id"),
        "item_count":      state.get("item_count"),
        "total_amount":    state.get("total_amount"),
        "pending":         bool(snapshot.next),
    }

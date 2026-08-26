from __future__ import annotations
from typing import Annotated, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState:
    messages:        Annotated[list[BaseMessage], add_messages]
    user_message:    str | None
    intent:          str | None   # food | instamart | dineout | combined | unclear
    cart:            str | None
    approval_status: str | None   # approved | declined
    order_status:    str | None
    swiggy_order_id: str | None

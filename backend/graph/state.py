from __future__ import annotations
from typing import Annotated, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState:
    messages: Annotated[list[BaseMessage], add_messages]
    user_message: str | None
    intent: str | None  #food | instamart | dineout | combined | unclear
    thread_id: str | None
    conversation_id: str | None
    address_id: str | None
    cart: dict[str, Any] | None
    coupon: str | None
    approval_status: str | None #pending | approved | declined
    order_id: str | None
    swiggy_order_id: str | None
    order_status: str | None
    error: str | None
    # dineout
    restaurant_id: str | None
    booking_slot: str | None
    party_size: int | None

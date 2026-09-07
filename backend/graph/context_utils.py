"""
backend/graph/context_utils.py
───────────────────────────────
Two targeted fixes for the 8 K token-budget problem diagnosed by
probe_menu_auto.py:

  Fix 1 — strip_image_urls()
    The Swiggy MCP tool text embeds full CDN URLs for every menu item
    (41 URLs in a Domino's menu = ~800–1 200 wasted tokens).  The LLM
    never renders images — it only needs the name, price, and ID.
    This regex removes every https://media-assets.swiggy.com/… URL
    from a tool-result string before it enters the context window.

  Fix 2 — make_trim_hook()
    Returns a LangGraph pre_model_hook that trims the message list
    *inside* the ReAct loop to a token budget before each LLM call.
    Strategy: always keep the system prompt + the last two human/AI
    pairs + ALL tool messages that have no preceding AI pair kept (so
    the LLM never sees an orphaned ToolMessage).
    Falls back to langchain_core.messages.trim_messages for the
    token counting.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    trim_messages,
)

# ── Fix 1: strip CDN image URLs ───────────────────────────────────────────────
# Matches both bare URLs and markdown-image syntax: [image: https://…]
_IMAGE_URL_RE = re.compile(
    r"""
    (?:                          # optional markdown [image: …] wrapper
        \[image:\s*
        https?://media-assets\.swiggy\.com[^\]]*
        \]
    )
    |
    (?:                          # bare URL (possibly with trailing comma/space)
        https?://media-assets\.swiggy\.com\S*
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def strip_image_urls(text: str) -> str:
    """Remove all Swiggy CDN image URLs from a tool-result string.

    Leaves everything else (name, price, ID, categories) intact.
    A trailing comma+space left after the URL is also cleaned up.
    """
    cleaned = _IMAGE_URL_RE.sub("", text)
    # Collapse ", ," or " , " artifacts left by removal
    cleaned = re.sub(r",\s*,", ",", cleaned)
    # Collapse double spaces
    cleaned = re.sub(r"  +", " ", cleaned)
    return cleaned.strip()


def _apply_strip_to_message(msg: BaseMessage) -> BaseMessage:
    """Return a copy of msg with image URLs stripped from its content."""
    if not isinstance(msg, ToolMessage):
        return msg
    content = msg.content
    if isinstance(content, str):
        new_content = strip_image_urls(content)
    elif isinstance(content, list):
        new_content = [
            {**block, "text": strip_image_urls(block["text"])}
            if isinstance(block, dict) and "text" in block
            else block
            for block in content
        ]
    else:
        return msg
    # ToolMessage is immutable; rebuild via model_copy (Pydantic v2) or copy
    try:
        return msg.model_copy(update={"content": new_content})
    except AttributeError:
        cloned = msg.__class__(**{**msg.__dict__, "content": new_content})
        return cloned


# ── Fix 2: pre_model_hook — trim history to token budget ─────────────────────
#
# Why pre_model_hook instead of hand-rolling truncation in the node?
# • It runs *inside* the ReAct loop — every LLM call, not just node entry.
# • LangGraph passes the full in-flight state dict; we return {"messages": …}.
# • trim_messages from langchain_core handles the orphan-ToolMessage
#   constraint for us (strategy="last", include_system=True).
#
# Groq llama-3.3-70b-versatile hard limit: 8 192 tokens.
# We target 6 000 to leave breathing room for the model's output.
_TOKEN_BUDGET = 6_000


def _count_tokens(text: str) -> int:
    """Cheap char-based token estimate (4 chars ≈ 1 token)."""
    return len(text) // 4


def _msg_token_count(msg: BaseMessage) -> int:
    content = msg.content
    if isinstance(content, str):
        return _count_tokens(content)
    if isinstance(content, list):
        return sum(
            _count_tokens(b.get("text", "") if isinstance(b, dict) else str(b))
            for b in content
        )
    return 0


def make_trim_hook(token_budget: int = _TOKEN_BUDGET):
    """Return a LangGraph pre_model_hook that:

    1. Strips image URLs from every ToolMessage.
    2. Trims the message list to *token_budget* using trim_messages,
       keeping the system prompt and always ensuring ToolMessages are
       preceded by the AI message that requested them.

    Usage:
        agent = create_react_agent(
            llm, tools, prompt=PROMPT,
            pre_model_hook=make_trim_hook(),
        )
    """

    def _hook(state: dict[str, Any]) -> dict[str, Any]:
        messages: list[BaseMessage] = state.get("messages", [])

        # Step A — strip image URLs from all ToolMessages in-place
        messages = [_apply_strip_to_message(m) for m in messages]

        # Step B — trim to token budget
        # trim_messages strategy="last":
        #   • Keeps the system message.
        #   • Counts from the END of the list.
        #   • Never leaves an orphaned ToolMessage (drops its paired AI too).
        try:
            trimmed = trim_messages(
                messages,
                max_tokens=token_budget,
                strategy="last",
                token_counter=_msg_token_count,
                include_system=True,
                allow_partial=False,
                start_on="human",   # always start trim boundary on a human turn
            )
        except Exception:
            # If trim_messages fails for any reason, fall back gracefully
            trimmed = messages

        return {"messages": trimmed}

    return _hook


# Convenience singleton — all subgraphs import this directly
trim_hook = make_trim_hook()

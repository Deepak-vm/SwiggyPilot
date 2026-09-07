#!/usr/bin/env python3
"""
probe_menu_payload.py
─────────────────────
Standalone diagnostic: call get_restaurant_menu via raw JSON-RPC,
*completely* bypassing the agent / LangChain / conversation history.

Goal: measure the bare payload size so we can confirm (or rule out) that a
large menu response is pushing the LLM over its context / token-budget limit.

Usage
──────
    python probe_menu_payload.py <addressId> <restaurantId>

    # or run with no args — the script will prompt you
    python probe_menu_payload.py

The addressId / restaurantId must be real values from your Swiggy account
(grab them from a previous search_restaurants + get_addresses call).
"""

import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ── 1. Load .env ──────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

FOOD_URL = os.getenv("SWIGGY_MCP_FOOD_URL", "https://mcp.swiggy.com/food")

# ── 2. Re-use the existing auth helper (handles PKCE / token cache) ──────────
sys.path.insert(0, str(Path(__file__).parent))
from backend.mcp.swiggy_client import get_token  # noqa: E402


# ── 3. Raw JSON-RPC call — no LangChain, no agent, no history ────────────────
async def raw_get_restaurant_menu(address_id: str, restaurant_id: str):
    """POST a single JSON-RPC 2.0 request and return the parsed response."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_restaurant_menu",
            "arguments": {
                "addressId": address_id,
                "restaurantId": restaurant_id,
            },
        },
        "id": 1,
    }

    token = get_token()          # triggers browser login if token is expired
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    print(f"\n📡  POST {FOOD_URL}")
    print(f"    addressId    = {address_id!r}")
    print(f"    restaurantId = {restaurant_id!r}")
    print("    (no agent, no history, no system prompt)\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(FOOD_URL, json=payload, headers=headers)

    resp.raise_for_status()

    # The server may respond with plain JSON or with SSE (text/event-stream).
    content_type = resp.headers.get("content-type", "")
    raw_text = resp.text

    if "text/event-stream" in content_type:
        # Extract the JSON object from the SSE stream (last `data:` line)
        data_lines = [
            line[len("data:"):].strip()
            for line in raw_text.splitlines()
            if line.startswith("data:")
        ]
        raw_json = "\n".join(data_lines)
    else:
        raw_json = raw_text

    return json.loads(raw_json), raw_json


# ── 4. Reporting helpers ──────────────────────────────────────────────────────
def _token_estimate(text: str) -> int:
    """Rough token estimate: ~4 chars / token (GPT-4o / Claude rule of thumb)."""
    return len(text) // 4


SEPARATOR = "─" * 72


def print_report(parsed: dict, raw_json: str) -> None:
    byte_size  = len(raw_json.encode("utf-8"))
    char_count = len(raw_json)
    tok_est    = _token_estimate(raw_json)

    # ── Pretty-print the full response ──────────────────────────────────────
    print(SEPARATOR)
    print("RAW RESPONSE (pretty-printed)")
    print(SEPARATOR)
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    lines = pretty.splitlines()
    if len(lines) > 200:
        print("\n".join(lines[:200]))
        print(f"\n  … {len(lines) - 200} more lines (see menu_payload_dump.json) …")
    else:
        print(pretty)

    # ── Extract key facts from the data payload ──────────────────────────────
    data = (
        parsed.get("result", {})
              .get("content", [{}])[0]
              .get("text", "{}")
    )
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}

    inner_data   = data.get("data", {})
    total_items  = inner_data.get("totalItems", "?")
    total_cats   = inner_data.get("totalCategories", "?")
    truncated    = inner_data.get("truncated", False)
    rest_name    = inner_data.get("restaurant", {}).get("name", "?")

    # ── Payload size report ───────────────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("PAYLOAD SIZE ANALYSIS")
    print(SEPARATOR)
    print(f"  Restaurant   : {rest_name}")
    print(f"  Items        : {total_items}  (categories: {total_cats})")
    print(f"  Truncated    : {'YES — menu capped at 150 items' if truncated else 'No'}")
    print(f"\n  Raw bytes    : {byte_size:,} B   ({byte_size / 1024:.1f} KB)")
    print(f"  Chars        : {char_count:,}")
    print(f"  Token est.   : ~{tok_est:,}  (chars / 4, GPT-4o / Claude rule of thumb)")

    # ── Context-budget verdict ────────────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("TOKEN-BUDGET VERDICT")
    print(SEPARATOR)

    # Groq llama-3.3-70b-versatile: 8,192 token context window
    # System prompt + tool schemas + conversation history ~= 4-5 K tokens
    # That leaves ~3-4 K for the tool response.
    GROQ_CTX           = 8_192
    OVERHEAD_ESTIMATE  = 4_500   # system prompt + 6 tool schemas + history
    BUDGET_LEFT        = GROQ_CTX - OVERHEAD_ESTIMATE

    if tok_est > BUDGET_LEFT:
        surplus = tok_est - BUDGET_LEFT
        print(f"  OVER BUDGET by ~{surplus:,} tokens")
        print(f"  Menu response alone (~{tok_est:,} tok) exceeds the")
        print(f"  estimated remaining context ({BUDGET_LEFT:,} tok) after")
        print(f"  system prompt + tool schemas + history overhead.")
        print()
        print("  --> This CONFIRMS the token-budget hypothesis.")
        print("  --> Fixes to consider:")
        print("      1. Use search_menu instead of get_restaurant_menu")
        print("         (returns fewer, query-focused items).")
        print("      2. Filter out-of-stock items before forwarding to LLM.")
        print("      3. Upgrade to a 32K+ context model (e.g. llama-3.1-70b).")
    elif tok_est > BUDGET_LEFT * 0.75:
        print(f"  TIGHT -- {tok_est:,} tokens used out of ~{BUDGET_LEFT:,} available.")
        print("  Leaves little room for follow-up turns or longer histories.")
        print("  --> Worth trimming the response or raising context window.")
    else:
        print(f"  OK -- {tok_est:,} tokens, well within ~{BUDGET_LEFT:,} available.")
        print("  --> Token budget is NOT the culprit. Look elsewhere.")

    print(f"\n{SEPARATOR}\n")

    # ── Save full JSON to disk for manual inspection ──────────────────────────
    out_path = Path(__file__).parent / "menu_payload_dump.json"
    out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False))
    print(f"  Full response saved --> {out_path}")


# ── 5. Entry point ────────────────────────────────────────────────────────────
async def main():
    args = sys.argv[1:]

    if len(args) >= 2:
        address_id    = args[0]
        restaurant_id = args[1]
    else:
        print(textwrap.dedent("""
            get_restaurant_menu  --  raw payload probe
            Bypasses agent/LangChain to measure bare JSON-RPC payload size.

            You need a real addressId and restaurantId from your Swiggy account.
            Grab them from the main app output or from a LangSmith trace.
        """))
        address_id    = input("  Enter addressId    : ").strip()
        restaurant_id = input("  Enter restaurantId : ").strip()

    parsed, raw_json = await raw_get_restaurant_menu(address_id, restaurant_id)
    print_report(parsed, raw_json)


if __name__ == "__main__":
    asyncio.run(main())

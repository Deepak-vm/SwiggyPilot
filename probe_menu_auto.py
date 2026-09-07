#!/usr/bin/env python3
"""
probe_menu_auto.py  —  get_restaurant_menu payload probe + before/after comparison.
Chain: get_addresses → search_restaurants → get_restaurant_menu (raw JSON-RPC).
Reports token counts BEFORE and AFTER image-URL stripping.
"""
import asyncio, json, os, re, sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
FOOD_URL = os.getenv("SWIGGY_MCP_FOOD_URL", "https://mcp.swiggy.com/food")
sys.path.insert(0, str(Path(__file__).parent))
from backend.mcp.swiggy_client import get_token
from backend.graph.context_utils import strip_image_urls

SEP = "─" * 70


async def rpc(client, headers, tool, args):
    payload = {"jsonrpc":"2.0","method":"tools/call","id":1,
               "params":{"name":tool,"arguments":args}}
    r = await client.post(FOOD_URL, json=payload, headers=headers)
    r.raise_for_status()
    ct, raw = r.headers.get("content-type",""), r.text
    if "text/event-stream" in ct:
        raw = "\n".join(ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:"))
    return json.loads(raw), raw


def content_text(parsed):
    try:
        return parsed["result"]["content"][0]["text"]
    except Exception:
        return ""


def tok(s): return len(s) // 4


async def main():
    # ── 1. Auth ───────────────────────────────────────────────────────────────
    print("\n[1/4] OAuth token …")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    print("      Token OK.\n")

    async with httpx.AsyncClient(timeout=30.0) as client:

        # ── 2. get_addresses ──────────────────────────────────────────────────
        print("[2/4] get_addresses …")
        parsed_addr, _ = await rpc(client, headers, "get_addresses", {})
        addr_text = content_text(parsed_addr)

        address_id = None
        try:
            d = json.loads(addr_text)
            addrs = d.get("data",{}).get("addresses") or d.get("addresses") or []
            if addrs:
                address_id = addrs[0].get("id") or addrs[0].get("addressId")
        except Exception:
            pass
        if not address_id:
            m = re.search(r'\(ID:\s*([^\)]+)\)', addr_text)
            if m: address_id = m.group(1).strip()
        if not address_id:
            print("      No addressId found. Raw:"); print(addr_text[:500]); sys.exit(1)
        print(f"      addressId = {address_id!r}\n")

        # ── 3. search_restaurants ─────────────────────────────────────────────
        print("[3/4] search_restaurants(query='pizza') …")
        parsed_sr, _ = await rpc(client, headers, "search_restaurants",
                                 {"addressId": address_id, "query": "pizza"})
        sr_text = content_text(parsed_sr)

        restaurant_id = None
        rest_name_from_search = "?"
        # The text may be multiple JSON objects concatenated; grab the first
        first_json_end = sr_text.find('\n{', 1)
        first_chunk = sr_text if first_json_end == -1 else sr_text[:first_json_end]
        try:
            d = json.loads(first_chunk)
            rests = d.get("restaurants") or []
            if rests:
                restaurant_id = rests[0].get("id") or rests[0].get("restaurantId")
                rest_name_from_search = rests[0].get("name", "?")
        except Exception:
            pass
        if not restaurant_id:
            m = re.search(r'"id"\s*:\s*"(\d+)"', sr_text)
            if m: restaurant_id = m.group(1)
        if not restaurant_id:
            print("      No restaurantId found. Raw:"); print(sr_text[:500]); sys.exit(1)
        print(f"      restaurantId = {restaurant_id!r}  ({rest_name_from_search})\n")

        # ── 4. get_restaurant_menu ────────────────────────────────────────────
        print("[4/4] get_restaurant_menu …")
        parsed_menu, raw_envelope = await rpc(
            client, headers, "get_restaurant_menu",
            {"addressId": address_id, "restaurantId": restaurant_id})

    tool_text = content_text(parsed_menu)
    stripped  = strip_image_urls(tool_text)

    # ── Counts ────────────────────────────────────────────────────────────────
    img_urls  = len(re.findall(r'https?://media-assets\.swiggy\.com\S*', tool_text))
    lines_before = len(tool_text.splitlines())
    lines_after  = len(stripped.splitlines())

    before_bytes = len(tool_text.encode("utf-8"))
    after_bytes  = len(stripped.encode("utf-8"))
    before_tok   = tok(tool_text)
    after_tok    = tok(stripped)
    saved_tok    = before_tok - after_tok
    envelope_kb  = len(raw_envelope.encode("utf-8")) / 1024

    GROQ_CTX = 8_192; OVERHEAD = 4_500; BUDGET = GROQ_CTX - OVERHEAD

    print(f"\n{SEP}")
    print("BEFORE / AFTER  —  image URL stripping (Fix 1)")
    print(SEP)
    print(f"  Restaurant      : {rest_name_from_search}  (ID {restaurant_id})")
    print(f"  Image URLs found: {img_urls}")
    print()
    print(f"  {'Metric':<26} {'BEFORE':>10}  {'AFTER':>10}  {'Saved':>8}")
    print(f"  {'─'*26} {'─'*10}  {'─'*10}  {'─'*8}")
    print(f"  {'Bytes (tool text)':<26} {before_bytes:>10,}  {after_bytes:>10,}  {before_bytes-after_bytes:>+8,}")
    print(f"  {'Lines':<26} {lines_before:>10}  {lines_after:>10}  {lines_before-lines_after:>+8}")
    print(f"  {'Token estimate (÷4)':<26} {before_tok:>10,}  {after_tok:>10,}  {saved_tok:>+8,}")
    print(f"\n  JSON-RPC envelope (wire) : {envelope_kb:.1f} KB  (model never sees this)")

    print(f"\n{SEP}")
    print("TOKEN-BUDGET VERDICT  (after Fix 1)")
    print(SEP)
    print(f"  Groq window     : {GROQ_CTX:,} tok")
    print(f"  Overhead (est.) : ~{OVERHEAD:,} tok  (sys-prompt + 6 schemas + history)")
    print(f"  Budget left     : ~{BUDGET:,} tok")
    print(f"  Menu uses NOW   : ~{after_tok:,} tok  ({after_tok*100//BUDGET}% of budget)")
    print(f"  Previously used : ~{before_tok:,} tok  ({before_tok*100//BUDGET}% of budget)")
    print()
    if after_tok > BUDGET:
        print(f"  STILL OVER BUDGET by ~{after_tok-BUDGET:,} tok — Fix 2 (trim_hook) critical.")
    elif after_tok > BUDGET * 0.75:
        print(f"  TIGHT — Fix 2 (trim_hook) gives additional headroom for multi-turn.")
    else:
        print(f"  FITS comfortably. Fix 2 (trim_hook) prevents future blowout from history.")
    print(SEP)

    # ── Save dumps ────────────────────────────────────────────────────────────
    out = Path(__file__).parent / "menu_payload_dump.json"
    out.write_text(json.dumps(parsed_menu, indent=2, ensure_ascii=False))

    out_stripped = Path(__file__).parent / "menu_payload_stripped.txt"
    out_stripped.write_text(stripped)

    print(f"\n  Full JSON saved    → {out}")
    print(f"  Stripped text      → {out_stripped}")
    print()

if __name__ == "__main__":
    asyncio.run(main())

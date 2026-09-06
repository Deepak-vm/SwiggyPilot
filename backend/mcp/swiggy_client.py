import os
import base64
import hashlib
import secrets
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

FOOD_URL     = os.getenv("SWIGGY_MCP_FOOD_URL",     "https://mcp.swiggy.com/food")
IM_URL       = os.getenv("SWIGGY_MCP_INSTAMART_URL", "https://mcp.swiggy.com/im")
DINEOUT_URL  = os.getenv("SWIGGY_MCP_DINEOUT_URL",   "https://mcp.swiggy.com/dineout")
REDIRECT_URI = os.getenv("SWIGGY_OAUTH_REDIRECT_URI", "http://localhost:7999/oauth/callback")

REGISTER_URL = "https://mcp.swiggy.com/auth/register"
AUTH_URL     = "https://mcp.swiggy.com/auth/authorize"
TOKEN_URL    = "https://mcp.swiggy.com/auth/token"

_client_id: str | None = None
_token: str | None = None
_token_expires_at: datetime | None = None


def _pkce_pair() -> tuple[str, str]:
    verifier  = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _register() -> str:
    """Dynamic Client Registration — once per process."""
    global _client_id
    if _client_id:
        return _client_id
    r = httpx.post(REGISTER_URL, json={
        "client_name": "SwiggyPilot",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    r.raise_for_status()
    _client_id = r.json()["client_id"]
    return _client_id


def _wait_for_callback() -> str:
    """One-shot HTTP server on localhost — blocks until Swiggy redirects, returns the code."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    code_holder: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            code_holder["code"] = parse_qs(urlparse(self.path).query).get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px;
                    background:#111;color:#fff">
                <h2 style="color:#4ade80">&#10003; Authenticated!</h2>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
            """)

        def log_message(self, *_):
            pass  # silence request logs

    port   = urlparse(REDIRECT_URI).port or 8000
    server = HTTPServer(("localhost", port), Handler)
    server.handle_request()   # blocks until exactly one GET arrives
    server.server_close()
    return code_holder.get("code", "")


def get_token() -> str:
    """Return a cached or fresh Bearer token (triggers browser login if needed)."""
    global _token, _token_expires_at

    now = datetime.now(timezone.utc)
    if _token and _token_expires_at and now < _token_expires_at - timedelta(seconds=60):
        return _token

    client_id           = _register()
    verifier, challenge = _pkce_pair()

    auth_url = AUTH_URL + "?" + urlencode({
        "response_type":         "code",
        "client_id":             client_id,
        "redirect_uri":          REDIRECT_URI,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
        "state":                 secrets.token_urlsafe(16),
        "scope":                 "mcp:tools",
    })

    print("\nOpening browser for Swiggy login (phone + OTP)...")
    webbrowser.open(auth_url)

    code = _wait_for_callback()
    if not code:
        raise RuntimeError("OAuth callback received no code — try again.")

    r = httpx.post(TOKEN_URL, json={
        "grant_type":    "authorization_code",
        "client_id":     client_id,
        "code":          code,
        "code_verifier": verifier,
        "redirect_uri":  REDIRECT_URI,
    })
    r.raise_for_status()
    data = r.json()

    _token            = data["access_token"]
    _token_expires_at = now + timedelta(seconds=data.get("expires_in", 432000))
    print("Authenticated with Swiggy MCP.\n")
    return _token


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_token()}"}


def get_client(verticals: list[str] | None = None) -> MultiServerMCPClient:
    """Return a MultiServerMCPClient wired to the requested verticals."""
    all_servers = {
        "food":      {"url": FOOD_URL,    "transport": "streamable_http", "headers": _headers()},
        "instamart": {"url": IM_URL,      "transport": "streamable_http", "headers": _headers()},
        "dineout":   {"url": DINEOUT_URL, "transport": "streamable_http", "headers": _headers()},
    }
    selected = verticals or list(all_servers)
    return MultiServerMCPClient({k: v for k, v in all_servers.items() if k in selected})


async def get_tools(
    verticals: list[str] | None = None,
    allowed_tools: list[str] | None = None,
) -> list:
    """Return LangChain-compatible tools for the given verticals.

    Args:
        verticals:     Which MCP servers to connect to (food / instamart / dineout).
        allowed_tools: If supplied, only return tools whose name is in this list.
                       Use this to expose the minimum schemas to each LLM call.
    """
    tools = await get_client(verticals).get_tools()
    if allowed_tools:
        tools = [t for t in tools if t.name in allowed_tools]
    return tools

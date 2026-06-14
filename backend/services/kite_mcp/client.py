"""
Kite MCP client — Streamable-HTTP transport, read-only.

Handshake:
  POST /mcp  {jsonrpc:2.0, method:initialize, ...}
    → response header mcp-session-id
  POST /mcp  {method:notifications/initialized}  (no id)
    → ack

Auth: call tools/call login → returns login_url → user completes Zerodha OAuth
→ same session becomes authenticated.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

_MCP_URL = "https://mcp.kite.trade/mcp"
_TIMEOUT = 30

_HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_READ_TOOLS = frozenset({
    "get_holdings",
    "get_positions",
    "get_orders",
    "get_trades",
    "get_margins",
    "get_mf_holdings",
    "get_profile",
    "get_gtts",
    "get_order_history",
    "get_order_trades",
    "get_ltp",
    "get_quotes",
    "get_ohlc",
    "get_historical_data",
    "search_instruments",
    "login",
})

_WRITE_TOOLS = frozenset({
    "place_order",
    "modify_order",
    "cancel_order",
    "place_gtt_order",
    "modify_gtt_order",
    "delete_gtt_order",
})


def _session_headers(sid: str) -> dict[str, str]:
    return {**_HEADERS_BASE, "mcp-session-id": sid}


def _parse_response(raw: httpx.Response) -> dict:
    ct = raw.headers.get("content-type", "")
    text = raw.text.strip()
    if not text:
        return {}
    if "text/event-stream" in ct:
        for line in text.splitlines():
            if line.startswith("data: "):
                chunk = line[6:].strip()
                if chunk and chunk != "[DONE]":
                    try:
                        return json.loads(chunk)
                    except Exception:
                        continue
        return {}
    try:
        return raw.json()
    except Exception:
        return {}


async def open_session() -> str:
    """Perform initialize + notifications/initialized handshake; return session id."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        init_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "crest", "version": "1.0"},
            },
        }
        r = await client.post(_MCP_URL, headers=_HEADERS_BASE, json=init_body)
        r.raise_for_status()
        sid = r.headers.get("mcp-session-id")
        if not sid:
            data = _parse_response(r)
            sid = (data.get("result") or {}).get("sessionId") or data.get("sessionId")
        if not sid:
            raise RuntimeError(f"Kite MCP: no session-id in initialize response. status={r.status_code}")

        notif_body = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        await client.post(_MCP_URL, headers=_session_headers(sid), json=notif_body)

    log.info("kite_mcp: session opened sid=%s", sid[:16])
    return sid


async def call_tool(sid: str, name: str, args: dict | None = None) -> Any:
    """Call a Kite MCP tool by name. Returns the result payload (parsed JSON)."""
    body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": name, "arguments": args or {}},
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(_MCP_URL, headers=_session_headers(sid), json=body)
    r.raise_for_status()
    data = _parse_response(r)
    result = data.get("result", data)
    if isinstance(result, dict) and result.get("isError"):
        raise RuntimeError(f"Kite MCP tool error: {result.get('content', result)}")
    content = result.get("content") if isinstance(result, dict) else result
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except Exception:
                    return item["text"]
        return content
    return content


async def list_tools(sid: str) -> list[dict]:
    body = {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(_MCP_URL, headers=_session_headers(sid), json=body)
    r.raise_for_status()
    data = _parse_response(r)
    return (data.get("result") or {}).get("tools", [])


async def start_login(sid: str) -> str:
    """Call the login tool; return the Kite login URL.

    The MCP login tool returns a human-facing text blob (warning + markdown link),
    so extract the kite.zerodha.com connect URL from whatever shape comes back.
    """
    import re

    result = await call_tool(sid, "login")
    if isinstance(result, dict):
        url = result.get("url") or result.get("login_url") or result.get("loginUrl")
        if url:
            return url
    text = result if isinstance(result, str) else json.dumps(result)
    m = re.search(r"https://kite\.zerodha\.com/connect/login\?[^\s\)\"']+", text)
    if m:
        return m.group(0)
    raise RuntimeError(f"Kite login tool returned unexpected shape: {result!r}")


async def is_authenticated(sid: str) -> bool:
    """Probe get_profile to test if session is authenticated."""
    try:
        result = await call_tool(sid, "get_profile")
        return bool(result)
    except Exception:
        return False


async def get_ltps(sid: str, symbols: list[str]) -> dict[str, float]:
    """Live last-traded price per NSE equity symbol via Kite (accurate, free with a session).
    Returns {symbol: ltp}; empty dict on any failure so callers fall back to yfinance."""
    if not symbols:
        return {}
    try:
        res = await call_tool(sid, "get_ltp", {"instruments": [f"NSE:{s}" for s in symbols]})
    except Exception:
        return {}
    out: dict[str, float] = {}
    if isinstance(res, dict):
        for inst, val in res.items():
            sym = inst.split(":", 1)[1] if ":" in inst else inst
            if isinstance(val, dict) and val.get("last_price") is not None:
                try:
                    out[sym] = round(float(val["last_price"]), 2)
                except (TypeError, ValueError):
                    pass
    return out

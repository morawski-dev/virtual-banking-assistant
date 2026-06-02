"""Thin MCP client wrapper for flow handlers.

Replaces direct aiohttp calls to the mock Core Banking —
all requests go through the MCP server (port 8001).

Usage:
    from flows.mcp_client import call_mcp_tool

    data = await call_mcp_tool("core_banking_get_balance", {"customer_id": cid})
    # data is a dict parsed from the MCP tool's JSON response
"""

import json
import os
from typing import Any

from loguru import logger
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001/mcp")


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """Call an MCP tool and return the result as a dict.

    Each call opens a new StreamableHTTP connection (stateless).
    With 1-3 calls per conversation turn (~3-5 s), the ~5-10 ms overhead is negligible.

    Args:
        tool_name: Name of the MCP tool, e.g. 'core_banking_get_balance'.
        arguments: Dictionary of tool arguments.

    Returns:
        Dictionary parsed from the tool's JSON response.

    Raises:
        RuntimeError: When the tool returned no text content.
        Exception: On a connection error with the MCP server.
    """
    logger.debug(f"MCP call: {tool_name} args={list(arguments.keys())}")
    async with streamablehttp_client(url=MCP_SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)

    texts = [c.text for c in result.content if hasattr(c, "text") and c.text]
    if not texts:
        raise RuntimeError(f"MCP tool '{tool_name}' returned no text content")

    data: dict = json.loads(texts[0])
    logger.debug(f"MCP result: {tool_name} → status={data.get('status', 'ok')}")
    return data

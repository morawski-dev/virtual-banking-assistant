"""MCP server for the Virtual Assistant Demo.

Exposes 5 tools across 3 namespaces as an intermediate layer between
pipecat-flows handlers and the mock Core Banking API:

  core_banking_verify            — customer identity verification
  core_banking_get_balance       — account balance
  core_banking_find_transaction  — transaction search
  rag_search                     — search in the document repository
  mailer_send_offer              — send offer e-mail

Transport: streamable-http (port 8001) — production microservice pattern.

Local run:
    MOCK_CB_URL=http://localhost:8000 uv run python -m mcp_server.server

In docker-compose: service `mcp-server` with MOCK_CB_URL=http://mock-cb:8000.
"""

import json
import logging
import os

import aiohttp
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

MOCK_CB_URL = os.getenv("MOCK_CB_URL", "http://localhost:8000")

_host = os.getenv("MCP_HOST", "0.0.0.0")
_port = int(os.getenv("MCP_PORT", "8001"))

mcp = FastMCP("Core Banking MCP Server", host=_host, port=_port)


# ---------------------------------------------------------------------------
# Namespace: core_banking
# ---------------------------------------------------------------------------


@mcp.tool()
async def core_banking_verify(
    first_name: str, last_name: str, dob: str, card_last4: str
) -> str:
    """Verify customer identity based on personal data and card number.

    Args:
        first_name: Customer's first name, e.g. 'Jan'.
        last_name: Customer's last name, e.g. 'Kowalski'.
        dob: Date of birth in YYYY-MM-DD format, e.g. '1988-07-21'.
        card_last4: Last four digits of the card number as a string, e.g. '3476'.

    Returns:
        JSON string: {"verified": bool, "customer_id"?: str, "reason"?: str}
    """
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "dob": dob,
        "card_last4": card_last4,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{MOCK_CB_URL}/verify", json=payload) as resp:
                data = await resp.json()
        logger.info(
            "core_banking_verify: verified=%s customer_id=%s",
            data.get("verified"),
            data.get("customer_id"),
        )
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        logger.error("core_banking_verify failed: %s", exc)
        return json.dumps({"status": "error", "error": "verify_service_unavailable"})


@mcp.tool()
async def core_banking_get_balance(customer_id: str) -> str:
    """Retrieve the customer's account balance from Core Banking.

    Args:
        customer_id: Customer identifier, e.g. 'CUST-000001'.

    Returns:
        JSON string: {"customer_id": str, "balance_pln": float,
                      "account_number": str, "currency": str}
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{MOCK_CB_URL}/get_balance", params={"customer_id": customer_id}
            ) as resp:
                if resp.status != 200:
                    logger.error("core_banking_get_balance HTTP %s", resp.status)
                    return json.dumps({"status": "error", "error": "balance_unavailable"})
                data = await resp.json()
        logger.info("core_banking_get_balance: balance_pln=%s", data.get("balance_pln"))
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        logger.error("core_banking_get_balance failed: %s", exc)
        return json.dumps({"status": "error", "error": "balance_service_unavailable"})


@mcp.tool()
async def core_banking_find_transaction(
    customer_id: str, merchant: str, days: int = 30
) -> str:
    """Search for transactions in the customer's account history.

    Args:
        customer_id: Customer identifier.
        merchant: Merchant name fragment to match (case-insensitive), e.g. 'Zalando'.
        days: Number of days back to search (default 30).

    Returns:
        JSON string: {"customer_id": str, "query": {...},
                      "matches": [{"transaction_id", "merchant", "amount_pln",
                                    "booked_at", "description", "currency"}]}
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{MOCK_CB_URL}/find_transaction",
                params={"customer_id": customer_id, "merchant": merchant, "days": days},
            ) as resp:
                if resp.status != 200:
                    logger.error("core_banking_find_transaction HTTP %s", resp.status)
                    return json.dumps({"status": "error", "error": "transaction_unavailable"})
                data = await resp.json()
        matches = data.get("matches", [])
        logger.info(
            "core_banking_find_transaction: merchant='%s' matches=%d", merchant, len(matches)
        )
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        logger.error("core_banking_find_transaction failed: %s", exc)
        return json.dumps({"status": "error", "error": "transaction_service_unavailable"})


@mcp.tool()
async def core_banking_list_card_transactions(customer_id: str, limit: int = 5) -> str:
    """Return the customer's last N card transactions (default 5).

    Includes: card purchases (category='card_purchase'), ATM withdrawals
    ('atm_withdrawal'), charged card fees ('fee'). Sorted DESC by date.

    Args:
        customer_id: Customer identifier, e.g. 'CUST-000001'.
        limit: How many recent transactions to return (default 5, max 50).

    Returns:
        JSON string: {"customer_id": str, "limit": int,
                      "matches": [{"transaction_id", "merchant", "amount_pln",
                                    "booked_at", "description", "category",
                                    "channel"?, "related_transaction_id"?}]}
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{MOCK_CB_URL}/list_card_transactions",
                params={"customer_id": customer_id, "limit": limit},
            ) as resp:
                if resp.status != 200:
                    logger.error("core_banking_list_card_transactions HTTP %s", resp.status)
                    return json.dumps({"status": "error", "error": "card_history_unavailable"})
                data = await resp.json()
        matches = data.get("matches", [])
        logger.info(
            "core_banking_list_card_transactions: customer_id=%s matches=%d", customer_id, len(matches)
        )
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        logger.error("core_banking_list_card_transactions failed: %s", exc)
        return json.dumps({"status": "error", "error": "card_history_service_unavailable"})


# ---------------------------------------------------------------------------
# Namespace: rag
# ---------------------------------------------------------------------------


@mcp.tool()
async def rag_search(doc: str, query: str) -> str:
    """Search for information in the RAG product document repository.

    Args:
        doc: Document identifier, e.g. 'regulamin_konta_lokacyjnego.pdf'
             or 'konto_marzen.pdf'.
        query: Short query in Polish, e.g. 'oprocentowanie lokaty'.

    Returns:
        JSON string: {"doc": str, "query": str,
                      "chunks": [{"chunk_id", "text", "source"}]}
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{MOCK_CB_URL}/rag_search", params={"doc": doc, "query": query}
            ) as resp:
                if resp.status != 200:
                    logger.error("rag_search HTTP %s doc='%s'", resp.status, doc)
                    return json.dumps({"status": "error", "error": "rag_service_unavailable"})
                data = await resp.json()
        chunks = data.get("chunks", [])
        logger.info("rag_search: doc='%s' query='%s' chunks=%d", doc, query, len(chunks))
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        logger.error("rag_search failed: %s", exc)
        return json.dumps({"status": "error", "error": "rag_service_unavailable"})


# ---------------------------------------------------------------------------
# Namespace: mailer
# ---------------------------------------------------------------------------


@mcp.tool()
async def mailer_send_offer(customer_id: str, offer: str) -> str:
    """Send an offer to the customer's e-mail address registered in Core Banking.

    Log-only mailer — does not send real e-mails, writes to JSONL.

    Args:
        customer_id: Customer identifier.
        offer: Identifier of the offer to send, e.g. 'konto_marzen'.

    Returns:
        JSON string: {"status": "sent", "offer": str, "customer_id": str}
    """
    payload = {"customer_id": customer_id, "offer": offer}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{MOCK_CB_URL}/send_offer", json=payload) as resp:
                if resp.status != 200:
                    logger.error("mailer_send_offer HTTP %s offer='%s'", resp.status, offer)
                    return json.dumps({"status": "error", "error": "offer_service_unavailable"})
                data = await resp.json()
        logger.info(
            "mailer_send_offer: offer='%s' customer_id='%s' status=%s",
            offer, customer_id, data.get("status"),
        )
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        logger.error("mailer_send_offer failed: %s", exc)
        return json.dumps({"status": "error", "error": "offer_service_unavailable"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info(
        "Starting MCP server on %s:%s (MOCK_CB_URL=%s)", _host, _port, MOCK_CB_URL
    )
    mcp.run(transport="streamable-http")

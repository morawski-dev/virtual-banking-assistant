"""Async function handlers for pipecat-flows nodes.

Each handler receives (args: FlowArgs, flow_manager: FlowManager) and returns
a ConsolidatedFunctionResult: (FlowResult | None, NodeConfig | None).

Returning a NodeConfig as the second element triggers a node transition.
Returning None keeps the conversation in the current node.

All external API calls go through the MCP server (flows/mcp_client.py) instead
of hitting mock Core Banking directly — this satisfies the NF-04 requirement
for MCP-based sub-agent access to Core Banking, RAG, and email services.
"""

from datetime import datetime
from typing import Optional

from babel.dates import format_date
from babel.numbers import format_currency
from loguru import logger
from pipecat_flows import FlowArgs, FlowManager, FlowResult, NodeConfig

from flows.mcp_client import call_mcp_tool


def format_pln(amount: float) -> str:
    """Format PLN amount for Polish TTS: 15634.97 → '15 634,97 zł'."""
    return format_currency(amount, "PLN", locale="pl_PL", format_type="standard")


def format_booked_at_speech(iso: str) -> str:
    """Format ISO datetime string for Polish TTS: '2026-03-24T14:17:00+01:00' → '24 marca 2026'."""
    dt = datetime.fromisoformat(iso)
    return format_date(dt, format="long", locale="pl_PL")


async def handle_request_assistance(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Called by greeting node when the client states why they are calling.
    Saves intent and transitions to the identity (verification) node.
    """
    flow_manager.state["intent"] = args.get("reason", "")
    # Import here to avoid circular imports at module load time.
    from flows.nodes import create_identity_node

    return {"status": "ok"}, create_identity_node()


async def handle_submit_identity_slots(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, None]:
    """Called whenever the LLM picks up any identity slot from the client's speech.

    All parameters are optional — the client may provide name + DOB together in one
    turn and the card digits separately. The handler merges whatever was extracted
    into flow_manager.state["identity"].
    """
    identity: dict = flow_manager.state.setdefault("identity", {})
    for key in ("first_name", "last_name", "dob", "card_last4"):
        value: Optional[str] = args.get(key)
        if value:
            identity[key] = value.strip()
    logger.debug(f"identity slots so far: {list(identity.keys())}")
    return {"status": "ok"}, None


async def handle_confirm_card_and_verify(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, Optional[NodeConfig]]:
    """Called after the LLM echoes the card digits and the client confirms or rejects.

    If confirmed=True and all 4 slots are present, calls core_banking_verify via MCP.
    On success transitions to accounts node; on failure clears all slots
    so the LLM restarts identity collection.
    If confirmed=False, clears only card_last4 so the LLM asks for it again.
    """
    confirmed: bool = args.get("confirmed", False)
    identity: dict = flow_manager.state.setdefault("identity", {})

    card_last4_arg: Optional[str] = args.get("card_last4")
    if card_last4_arg:
        identity["card_last4"] = card_last4_arg.strip()

    if not confirmed:
        identity.pop("card_last4", None)
        logger.info("card echo rejected by client — clearing card_last4 slot")
        return {"status": "retry"}, None

    # Guard: ensure all slots were collected before calling verify.
    required_slots = ("first_name", "last_name", "dob", "card_last4")
    missing = [k for k in required_slots if not identity.get(k)]
    if missing:
        logger.warning(f"confirm_card_and_verify called with missing slots: {missing}")
        return {"status": "error", "error": f"missing_slots:{','.join(missing)}"}, None

    # Call MCP core_banking_verify.
    try:
        data = await call_mcp_tool(
            "core_banking_verify",
            {
                "first_name": identity["first_name"],
                "last_name": identity["last_name"],
                "dob": identity["dob"],
                "card_last4": identity["card_last4"],
            },
        )
    except Exception as exc:
        logger.error(f"MCP core_banking_verify failed: {exc}")
        return {"status": "error", "error": "verify_service_unavailable"}, None

    if data.get("verified"):
        customer_id: str = data["customer_id"]
        flow_manager.state["customer_id"] = customer_id
        logger.info(f"Verification successful — customer_id={customer_id}")
        if flow_manager.state.get("channel") == "chat":
            from flows.nodes import create_accounts_chat_node

            return {"status": "ok"}, create_accounts_chat_node()
        from flows.nodes import create_accounts_node

        return {"status": "ok"}, create_accounts_node()
    else:
        reason: str = data.get("reason", "Dane nie zgadzają się z naszymi zapisami.")
        logger.info(f"Verification failed: {reason}")
        # Clear identity so LLM collects all slots again.
        flow_manager.state["identity"] = {}
        return {"status": "error", "error": reason}, None


async def handle_get_balance(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, Optional[NodeConfig]]:
    """Calls core_banking_get_balance via MCP and returns formatted balance.

    In the chat channel transitions to accounts_chat_txn which omits get_balance,
    preventing the LLM from repeating the balance on subsequent requests.
    """
    customer_id: str = flow_manager.state.get("customer_id", "")
    try:
        data = await call_mcp_tool("core_banking_get_balance", {"customer_id": customer_id})
    except Exception as exc:
        logger.error(f"MCP core_banking_get_balance failed: {exc}")
        return {"status": "error", "error": "balance_service_unavailable"}, None

    if data.get("status") == "error":
        logger.error(f"core_banking_get_balance returned error: {data.get('error')}")
        return {"status": "error", "error": "balance_unavailable"}, None

    balance_str = format_pln(data["balance_pln"])
    logger.info(f"get_balance ok: {balance_str}")

    if flow_manager.state.get("channel") == "chat":
        from flows.nodes import create_accounts_chat_txn_node

        return {  # type: ignore[return-value]
            "status": "ok",
            "balance": balance_str,
            "account_number": data["account_number"],
        }, create_accounts_chat_txn_node()

    return {"status": "ok", "balance": balance_str, "account_number": data["account_number"]}, None  # type: ignore[return-value]


async def handle_find_transaction(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, None]:
    """Calls core_banking_find_transaction via MCP."""
    customer_id: str = flow_manager.state.get("customer_id", "")
    merchant: str = args.get("merchant", "")
    days: int = args.get("days", 30)
    try:
        data = await call_mcp_tool(
            "core_banking_find_transaction",
            {"customer_id": customer_id, "merchant": merchant, "days": days},
        )
    except Exception as exc:
        logger.error(f"MCP core_banking_find_transaction failed: {exc}")
        return {"status": "error", "error": "transaction_service_unavailable"}, None

    if data.get("status") == "error":
        logger.error(f"core_banking_find_transaction returned error: {data.get('error')}")
        return {"status": "error", "error": "transaction_unavailable"}, None

    matches = data.get("matches", [])
    for tx in matches:
        tx["amount_pln"] = format_pln(tx["amount_pln"])
        tx["booked_at_speech"] = format_booked_at_speech(tx["booked_at"])
    logger.info(f"find_transaction found {len(matches)} match(es) for merchant='{merchant}'")
    return {"status": "ok", "matches": matches}, None  # type: ignore[return-value]


async def handle_end_accounts_session(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Client indicated they are done — transition to closure."""
    from flows.nodes import create_closure_node

    return {"status": "ok"}, create_closure_node()


async def handle_route_to_products_rag(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Client asked about deposit/savings rates — transition to products_rag node."""
    from flows.nodes import create_products_rag_node

    return {"status": "ok"}, create_products_rag_node()


async def handle_rag_search(args: FlowArgs, flow_manager: FlowManager) -> tuple[FlowResult, None]:
    """Calls rag_search via MCP and returns chunks with citation hint."""
    doc: str = args.get("doc", "")
    query: str = args.get("query", "")
    try:
        data = await call_mcp_tool("rag_search", {"doc": doc, "query": query})
    except Exception as exc:
        logger.error(f"MCP rag_search failed: {exc}")
        return {"status": "error", "error": "rag_service_unavailable"}, None

    if data.get("status") == "error":
        logger.error(f"rag_search returned error: {data.get('error')}")
        return {"status": "error", "error": "rag_service_unavailable"}, None

    chunks = data.get("chunks", [])
    if not chunks:
        logger.info(f"rag_search empty: doc='{doc}' query='{query}'")
        return {"status": "empty", "doc": doc}, None  # type: ignore[return-value]

    citation_hint = chunks[0]["source"]
    logger.info(f"rag_search ok: doc='{doc}' query='{query}' chunks={len(chunks)}")
    return {"status": "ok", "doc": doc, "chunks": chunks, "citation_hint": citation_hint}, None  # type: ignore[return-value]


async def handle_send_offer(args: FlowArgs, flow_manager: FlowManager) -> tuple[FlowResult, None]:
    """Calls mailer_send_offer via MCP. Log-only mailer (no real SMTP)."""
    customer_id: str = flow_manager.state.get("customer_id", "")
    offer: str = args.get("offer", "")
    try:
        data = await call_mcp_tool(
            "mailer_send_offer", {"customer_id": customer_id, "offer": offer}
        )
    except Exception as exc:
        logger.error(f"MCP mailer_send_offer failed: {exc}")
        return {"status": "error", "error": "offer_service_unavailable"}, None

    if data.get("status") == "error":
        logger.error(f"mailer_send_offer returned error: {data.get('error')}")
        return {"status": "error", "error": "offer_service_unavailable"}, None

    logger.info(f"send_offer ok: offer='{offer}' customer_id='{customer_id}'")
    return {"status": "ok", "offer": data["offer"]}, None  # type: ignore[return-value]


async def handle_end_products_session(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Client finished the products_rag node — transition to closure."""
    from flows.nodes import create_closure_node

    return {"status": "ok"}, create_closure_node()


# ---------------------------------------------------------------------------
# Chat (S2) handlers
# ---------------------------------------------------------------------------


async def handle_list_card_transactions(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, Optional[NodeConfig]]:
    """Calls core_banking_list_card_transactions via MCP and returns formatted transactions.

    In the chat channel transitions to accounts_chat_fee_node which omits
    list_card_transactions, preventing the LLM from repeating it when asked about fees.
    """
    customer_id: str = flow_manager.state.get("customer_id", "")
    limit: int = args.get("limit", 5)
    try:
        data = await call_mcp_tool(
            "core_banking_list_card_transactions",
            {"customer_id": customer_id, "limit": limit},
        )
    except Exception as exc:
        logger.error(f"MCP core_banking_list_card_transactions failed: {exc}")
        return {"status": "error", "error": "card_history_unavailable"}, None

    if data.get("status") == "error":
        logger.error(f"core_banking_list_card_transactions returned error: {data.get('error')}")
        return {"status": "error", "error": "card_history_unavailable"}, None

    matches = data.get("matches", [])
    for tx in matches:
        tx["amount_pln"] = format_pln(tx["amount_pln"])
        tx["booked_at_long"] = format_booked_at_speech(tx["booked_at"])
    flow_manager.state["last_card_transactions"] = matches
    logger.info(f"list_card_transactions ok: {len(matches)} tx for customer_id={customer_id}")

    if flow_manager.state.get("channel") == "chat":
        from flows.nodes import create_accounts_chat_fee_node

        return {"status": "ok", "matches": matches}, create_accounts_chat_fee_node()  # type: ignore[return-value]

    return {"status": "ok", "matches": matches}, None  # type: ignore[return-value]


async def handle_explain_card_fee(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, None]:
    """Correlate the latest card fee with a RAG chunk from the fee schedule."""
    customer_id: str = flow_manager.state.get("customer_id", "")
    matches = flow_manager.state.get("last_card_transactions")
    if not matches:
        try:
            data = await call_mcp_tool(
                "core_banking_list_card_transactions",
                {"customer_id": customer_id, "limit": 10},
            )
        except Exception as exc:
            logger.error(f"MCP core_banking_list_card_transactions (refetch) failed: {exc}")
            return {"status": "error", "error": "fee_explanation_unavailable"}, None
        matches = data.get("matches", [])
        for tx in matches:
            tx["amount_pln"] = format_pln(tx["amount_pln"])
            tx["booked_at_long"] = format_booked_at_speech(tx["booked_at"])

    fee = next((t for t in matches if t.get("category") == "fee"), None)
    related = None
    if fee and fee.get("related_transaction_id"):
        related = next(
            (t for t in matches if t["transaction_id"] == fee["related_transaction_id"]),
            None,
        )

    try:
        rag = await call_mcp_tool(
            "rag_search",
            {"doc": "tabela_oplat.pdf", "query": "opłata wypłata bankomat spoza sieci Bank Demo"},
        )
    except Exception as exc:
        logger.error(f"MCP rag_search(tabela_oplat.pdf) failed: {exc}")
        return {"status": "error", "error": "fee_explanation_unavailable"}, None

    if rag.get("status") == "error":
        return {"status": "error", "error": "fee_explanation_unavailable"}, None

    chunks = rag.get("chunks", [])
    if not chunks:
        logger.info("rag_search(tabela_oplat.pdf) returned empty")
        return {"status": "empty", "doc": "tabela_oplat.pdf"}, None  # type: ignore[return-value]

    citation_hint = chunks[0]["source"]
    logger.info(f"explain_card_fee ok: fee={fee}, citation={citation_hint}")
    return {  # type: ignore[return-value]
        "status": "ok",
        "fee": fee,
        "related_transaction": related,
        "doc": "tabela_oplat.pdf",
        "chunks": chunks[:1],
        "citation_hint": citation_hint,
    }, None


async def handle_request_assistance_chat(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Called by greeting_chat node — saves intent and transitions to accounts_chat.

    No identity verification step: the client is pre-authenticated via web session
    (SSO/BankApp) and customer_id is injected at connection time in bot_webchat.py.
    """
    flow_manager.state["intent"] = args.get("reason", "")
    from flows.nodes import create_accounts_chat_node

    return {"status": "ok"}, create_accounts_chat_node()


async def handle_end_chat_session(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Client finished chat — transition to closure_chat and mark for WS close."""
    flow_manager.state["__last_node"] = "closure_chat"
    from flows.nodes import create_closure_chat_node

    return {"status": "ok"}, create_closure_chat_node()

"""Smoke test for the MCP Server.

Connects to a running MCP server, lists the tools and calls each of them
with test data (customer fixture Jan Kowalski, CUST-000001).

Requirements:
    - mock_cb running on http://localhost:8000
    - mcp_server running on http://localhost:8001

Run:
    # Terminal 1: mock_cb
    uv run uvicorn mock_cb.main:app --port 8000

    # Terminal 2: MCP server
    MOCK_CB_URL=http://localhost:8000 uv run python -m mcp_server.server

    # Terminal 3: test
    uv run python mcp_server/smoke_test.py
"""

import asyncio
import json
import os
import sys

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001/mcp")

EXPECTED_TOOLS = {
    "core_banking_verify",
    "core_banking_get_balance",
    "core_banking_find_transaction",
    "core_banking_list_card_transactions",
    "rag_search",
    "mailer_send_offer",
}


async def main() -> None:
    print(f"Connecting to MCP server at {MCP_URL} ...")
    async with streamablehttp_client(url=MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # --- List tools ---
            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}
            print(f"Available tools: {sorted(tool_names)}")
            missing = EXPECTED_TOOLS - tool_names
            if missing:
                print(f"FAIL: missing tools: {missing}", file=sys.stderr)
                sys.exit(1)

            # --- core_banking_verify (happy path) ---
            r = await session.call_tool(
                "core_banking_verify",
                arguments={
                    "first_name": "Jan",
                    "last_name": "Kowalski",
                    "dob": "1988-07-21",
                    "card_last4": "3476",
                },
            )
            d = json.loads(r.content[0].text)
            assert d.get("verified") is True, f"core_banking_verify failed: {d}"
            assert d.get("customer_id") == "CUST-000001", f"unexpected customer_id: {d}"
            print("  core_banking_verify  OK")

            # --- core_banking_verify (wrong data - should return verified=False) ---
            r = await session.call_tool(
                "core_banking_verify",
                arguments={
                    "first_name": "Anna",
                    "last_name": "Nowak",
                    "dob": "1990-01-01",
                    "card_last4": "0000",
                },
            )
            d = json.loads(r.content[0].text)
            assert d.get("verified") is False, f"core_banking_verify should fail: {d}"
            print("  core_banking_verify (wrong data)  OK")

            # --- core_banking_get_balance ---
            r = await session.call_tool(
                "core_banking_get_balance",
                arguments={"customer_id": "CUST-000001"},
            )
            d = json.loads(r.content[0].text)
            assert d.get("balance_pln") == 15634.97, f"unexpected balance: {d}"
            print(f"  core_banking_get_balance  OK  balance_pln={d['balance_pln']}")

            # --- core_banking_find_transaction ---
            r = await session.call_tool(
                "core_banking_find_transaction",
                arguments={
                    "customer_id": "CUST-000001",
                    "merchant": "Zalando",
                    "days": 365,
                },
            )
            d = json.loads(r.content[0].text)
            matches = d.get("matches", [])
            assert len(matches) >= 1, f"expected >=1 Zalando match, got: {d}"
            print(f"  core_banking_find_transaction  OK  matches={len(matches)}")

            # --- rag_search ---
            r = await session.call_tool(
                "rag_search",
                arguments={
                    "doc": "regulamin_konta_lokacyjnego.pdf",
                    "query": "oprocentowanie",
                },
            )
            d = json.loads(r.content[0].text)
            chunks = d.get("chunks", [])
            assert len(chunks) >= 1, f"expected >=1 RAG chunk, got: {d}"
            print(f"  rag_search  OK  chunks={len(chunks)}")

            # --- core_banking_list_card_transactions ---
            r = await session.call_tool(
                "core_banking_list_card_transactions",
                arguments={"customer_id": "CUST-000001", "limit": 5},
            )
            d = json.loads(r.content[0].text)
            matches = d.get("matches", [])
            assert len(matches) == 5, f"expected 5 card tx, got: {len(matches)}"
            categories = {m["category"] for m in matches}
            assert categories <= {"card_purchase", "atm_withdrawal", "fee"}, \
                f"unexpected categories: {categories}"
            fee_tx = [m for m in matches if m["category"] == "fee"]
            assert len(fee_tx) == 1, f"expected 1 fee tx, got: {fee_tx}"
            assert fee_tx[0]["amount_pln"] == -5.0, f"unexpected fee amount: {fee_tx[0]}"
            print(f"  core_banking_list_card_transactions  OK  matches={len(matches)}")

            # --- rag_search (tabela_oplat.pdf) ---
            r = await session.call_tool(
                "rag_search",
                arguments={
                    "doc": "tabela_oplat.pdf",
                    "query": "opłata wypłata bankomat spoza sieci Bank Demo",
                },
            )
            d = json.loads(r.content[0].text)
            chunks = d.get("chunks", [])
            assert len(chunks) >= 1, f"expected >=1 chunk for tabela_oplat.pdf, got: {d}"
            assert "par.2.2" in chunks[0]["source"], \
                f"expected par.2.2 in source, got: {chunks[0]['source']}"
            print(f"  rag_search (tabela_oplat.pdf)  OK  chunks={len(chunks)}")

            # --- mailer_send_offer ---
            r = await session.call_tool(
                "mailer_send_offer",
                arguments={
                    "customer_id": "CUST-000001",
                    "offer": "konto_marzen",
                },
            )
            d = json.loads(r.content[0].text)
            assert d.get("status") == "sent", f"send_offer failed: {d}"
            print(f"  mailer_send_offer  OK  status={d['status']}")

    print("\nAll MCP smoke tests PASSED.")


if __name__ == "__main__":
    asyncio.run(main())

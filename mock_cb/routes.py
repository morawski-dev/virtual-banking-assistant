import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from mock_cb.data import CUSTOMER, RAG_CHUNKS, TRANSACTIONS
from mock_cb.models import (
    BalanceResponse,
    FindTransactionResponse,
    ListCardTransactionsResponse,
    RagChunk,
    RagSearchResponse,
    SendOfferRequest,
    SendOfferResponse,
    Transaction,
    VerifyRequest,
    VerifyResponse,
)
from mock_cb.rag.retriever import search

logger = logging.getLogger(__name__)

router = APIRouter()

OFFERS_LOG = Path(__file__).parent / "data" / "sent_offers.jsonl"


@router.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest) -> VerifyResponse:
    logger.info(
        "verify attempt: first_name=%s last_name=%s dob=%s", req.first_name, req.last_name, req.dob
    )
    match = (
        req.first_name.strip().lower() == CUSTOMER["first_name"].lower()
        and req.last_name.strip().lower() == CUSTOMER["last_name"].lower()
        and req.dob.strip() == CUSTOMER["dob"]
        and req.card_last4 == CUSTOMER["card_last4"]
    )
    if match:
        logger.info("verify success: customer_id=%s", CUSTOMER["customer_id"])
        return VerifyResponse(verified=True, customer_id=CUSTOMER["customer_id"])
    logger.info("verify failed")
    return VerifyResponse(verified=False, reason="Dane nie zgadzają się z naszymi zapisami.")


@router.get("/get_balance", response_model=BalanceResponse)
def get_balance(customer_id: str) -> BalanceResponse:
    if customer_id != CUSTOMER["customer_id"]:
        raise HTTPException(status_code=404, detail="Customer not found")
    return BalanceResponse(
        customer_id=CUSTOMER["customer_id"],
        balance_pln=CUSTOMER["balance_pln"],
        account_number=CUSTOMER["account_number"],
    )


@router.get("/find_transaction", response_model=FindTransactionResponse)
def find_transaction(
    customer_id: str, merchant: str = "", days: Annotated[int, Query(ge=1)] = 30
) -> FindTransactionResponse:
    if customer_id != CUSTOMER["customer_id"]:
        raise HTTPException(status_code=404, detail="Customer not found")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    results = []
    for tx in TRANSACTIONS:
        if tx["customer_id"] != customer_id:
            continue
        if merchant and merchant.lower() not in tx["merchant"].lower():
            continue
        booked = datetime.fromisoformat(tx["booked_at"])
        if booked < cutoff:
            continue
        results.append(
            Transaction(
                transaction_id=tx["transaction_id"],
                merchant=tx["merchant"],
                amount_pln=tx["amount_pln"],
                booked_at=tx["booked_at"],
                description=tx["description"],
            )
        )

    results.sort(key=lambda t: t.booked_at, reverse=True)
    return FindTransactionResponse(
        customer_id=customer_id,
        query={"merchant": merchant, "days": days},
        matches=results,
    )


_CARD_CATEGORIES = {"card_purchase", "atm_withdrawal", "fee"}


@router.get("/list_card_transactions", response_model=ListCardTransactionsResponse)
def list_card_transactions(
    customer_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 5
) -> ListCardTransactionsResponse:
    if customer_id != CUSTOMER["customer_id"]:
        raise HTTPException(status_code=404, detail="Customer not found")
    rows = [
        tx for tx in TRANSACTIONS
        if tx["customer_id"] == customer_id and tx.get("category") in _CARD_CATEGORIES
    ]
    rows.sort(key=lambda t: t["booked_at"], reverse=True)
    return ListCardTransactionsResponse(
        customer_id=customer_id,
        limit=limit,
        matches=[Transaction(**r) for r in rows[:limit]],
    )


@router.get("/rag_search", response_model=RagSearchResponse)
def rag_search(request: Request, doc: str, query: str = "") -> RagSearchResponse:
    index = getattr(request.app.state, "rag_index", None)
    if index is not None:
        try:
            chunks = search(index, doc, query)
            if chunks:
                return RagSearchResponse(doc=doc, query=query, chunks=chunks)
            # Empty retrieval — fall through to stub (unknown doc or no matches)
        except Exception:
            logger.exception("RAG retrieval failed — falling back to stub")
    else:
        logger.warning("rag_search via stub fallback (index unavailable): doc=%s", doc)

    # Fallback: hardcoded RAG_CHUNKS fixture
    # (used when LlamaIndex/Qdrant index is unavailable — missing OPENAI_API_KEY,
    # Qdrant down, or init failure — see mock_cb/rag/indexer.py)
    stub = RAG_CHUNKS.get(doc)
    if stub is None:
        raise HTTPException(status_code=404, detail=f"Document '{doc}' not found in mock RAG store")
    return RagSearchResponse(
        doc=doc,
        query=query,
        chunks=[RagChunk(**c) for c in stub],
    )


@router.post("/send_offer", response_model=SendOfferResponse)
def send_offer(req: SendOfferRequest) -> SendOfferResponse:
    OFFERS_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "customer_id": req.customer_id,
        "offer": req.offer,
        "email": req.email,
        "sent_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    with OFFERS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("send_offer logged: customer_id=%s offer=%s", req.customer_id, req.offer)
    return SendOfferResponse(status="sent", offer=req.offer, customer_id=req.customer_id)

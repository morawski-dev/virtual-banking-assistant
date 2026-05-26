from typing import Literal

from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    first_name: str
    last_name: str
    dob: str  # ISO YYYY-MM-DD
    card_last4: str = Field(min_length=4, max_length=4)


class VerifyResponse(BaseModel):
    verified: bool
    customer_id: str | None = None
    reason: str | None = None


class BalanceResponse(BaseModel):
    customer_id: str
    balance_pln: float
    currency: Literal["PLN"] = "PLN"
    account_number: str


class Transaction(BaseModel):
    transaction_id: str
    merchant: str
    amount_pln: float
    currency: Literal["PLN"] = "PLN"
    booked_at: str
    description: str
    category: Literal["card_purchase", "atm_withdrawal", "fee", "other"] = "other"
    channel: str | None = None
    related_transaction_id: str | None = None


class FindTransactionResponse(BaseModel):
    customer_id: str
    query: dict
    matches: list[Transaction]


class ListCardTransactionsResponse(BaseModel):
    customer_id: str
    limit: int
    matches: list[Transaction]


class RagChunk(BaseModel):
    chunk_id: str
    text: str
    source: str


class RagSearchResponse(BaseModel):
    doc: str
    query: str
    chunks: list[RagChunk]


class SendOfferRequest(BaseModel):
    customer_id: str
    offer: str
    email: str | None = None


class SendOfferResponse(BaseModel):
    status: Literal["sent"]
    offer: str
    customer_id: str

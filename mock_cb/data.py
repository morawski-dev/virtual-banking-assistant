CUSTOMER = {
    "customer_id": "CUST-000001",
    "first_name": "Jan",
    "last_name": "Kowalski",
    "dob": "1988-07-21",  # YYYY-MM-DD
    "card_last4": "3476",
    "balance_pln": 15634.97,
    "account_number": "PL61109010140000071219812874",  # mock IBAN, test-safe
}

TRANSACTIONS = [
    {
        "transaction_id": "TXN-20260324-001",
        "customer_id": "CUST-000001",
        "merchant": "Zalando Lounge",
        "amount_pln": 540.01,
        "currency": "PLN",
        "booked_at": "2026-03-28T14:17:00+01:00",
        "description": "Zakup internetowy — Zalando Lounge",
    },
    {
        "transaction_id": "TXN-20260410-002",
        "customer_id": "CUST-000001",
        "merchant": "Biedronka",
        "amount_pln": 87.43,
        "currency": "PLN",
        "booked_at": "2026-04-10T10:05:00+02:00",
        "description": "Zakupy spożywcze — Biedronka",
    },
    {
        "transaction_id": "TXN-20260404-003",
        "customer_id": "CUST-000001",
        "merchant": "Allegro",
        "amount_pln": 229.99,
        "currency": "PLN",
        "booked_at": "2026-04-04T18:33:00+02:00",
        "description": "Zakup internetowy — Allegro",
    },
    {
        "transaction_id": "TXN-20251116-004",
        "customer_id": "CUST-000001",
        "merchant": "Zalando Lounge",
        "amount_pln": 149.90,
        "currency": "PLN",
        "booked_at": "2025-11-16T09:22:00+01:00",
        "description": "Zakup internetowy — Zalando Lounge",
    },
]

# Fallback fixture used when LlamaIndex/Qdrant index is unavailable
# (missing OPENAI_API_KEY, Qdrant down, or init failure — see mock_cb/rag/indexer.py).
RAG_CHUNKS: dict[str, list[dict]] = {
    "regulamin_konta_lokacyjnego.pdf": [
        {
            "chunk_id": "rkl-001",
            "text": (
                "Konto lokacyjne Bank Demo oferuje oprocentowanie 7% w skali roku "
                "z miesięczną kapitalizacją odsetek. Brak opłat za prowadzenie."
            ),
            "source": "Regulamin konta lokacyjnego Bank Demo, par.3.1",
        },
    ],
    "konto_marzen.pdf": [
        {
            "chunk_id": "rkm-001",
            "text": (
                "Konto Marzeń to konto osobiste z bonusem 300 zł dla nowych klientów "
                "przenoszących wpływy wynagrodzenia. Bez opłat miesięcznych przy aktywnym użytkowaniu."
            ),
            "source": "Oferta Konto Marzeń, str. 2",
        },
    ],
    "tabela_oplat.pdf": [
        {
            "chunk_id": "top-001",
            "text": (
                "Za każdą wypłatę gotówki z bankomatu, który nie należy do sieci Bank Demo "
                "ani do partnerów sieciowych, pobierana jest opłata w wysokości "
                "5,00 zł. Opłata księgowana jest jako odrębna transakcja kartowa z "
                "opisem \u201eOpłata \u2014 wypłata z bankomatu spoza sieci Bank Demo\u201d "
                "bezpośrednio po transakcji wypłaty środków."
            ),
            "source": "Tabela Opłat i Prowizji — Karta debetowa Premium 60+, par.2.2",
        },
    ],
}

CARD_TRANSACTIONS = [
    {
        "transaction_id": "TXN-20260414-010",
        "customer_id": "CUST-000001",
        "merchant": "Carrefour Market",
        "amount_pln": -142.58,
        "currency": "PLN",
        "booked_at": "2026-04-14T17:32:00+02:00",
        "description": "Płatność kartą — Carrefour Market",
        "category": "card_purchase",
        "channel": "pos",
    },
    {
        "transaction_id": "TXN-20260412-011",
        "customer_id": "CUST-000001",
        "merchant": "Orange Polska",
        "amount_pln": -89.00,
        "currency": "PLN",
        "booked_at": "2026-04-12T09:14:00+02:00",
        "description": "Płatność kartą — abonament Orange",
        "category": "card_purchase",
        "channel": "cnp",
    },
    {
        "transaction_id": "TXN-20260409-012",
        "customer_id": "CUST-000001",
        "merchant": "Bankomat Euronet, ul. Marszałkowska 1, Warszawa",
        "amount_pln": -400.00,
        "currency": "PLN",
        "booked_at": "2026-04-09T12:41:00+02:00",
        "description": "Wypłata z bankomatu spoza sieci Bank Demo",
        "category": "atm_withdrawal",
        "channel": "atm_out_of_network",
    },
    {
        "transaction_id": "TXN-20260409-013",
        "customer_id": "CUST-000001",
        "merchant": "Bank Demo Bank Polska",
        "amount_pln": -5.00,
        "currency": "PLN",
        "booked_at": "2026-04-09T12:41:01+02:00",
        "description": "Opłata — wypłata z bankomatu spoza sieci Bank Demo",
        "category": "fee",
        "channel": "atm_out_of_network",
        "related_transaction_id": "TXN-20260409-012",
    },
    {
        "transaction_id": "TXN-20260405-014",
        "customer_id": "CUST-000001",
        "merchant": "Apteka Dbam o Zdrowie",
        "amount_pln": -48.70,
        "currency": "PLN",
        "booked_at": "2026-04-05T11:02:00+02:00",
        "description": "Płatność kartą — apteka",
        "category": "card_purchase",
        "channel": "pos",
    },
    {
        "transaction_id": "TXN-20260402-015",
        "customer_id": "CUST-000001",
        "merchant": "PKP Intercity",
        "amount_pln": -189.00,
        "currency": "PLN",
        "booked_at": "2026-04-02T08:22:00+02:00",
        "description": "Płatność kartą — bilet kolejowy",
        "category": "card_purchase",
        "channel": "cnp",
    },
]

TRANSACTIONS = [*TRANSACTIONS, *CARD_TRANSACTIONS]

#!/usr/bin/env bash
# Mock CB smoke test — run against a running instance.
# Usage: bash mock_cb/curl-smoke.sh
# Or against docker compose network: MOCK_CB_URL=http://localhost:8000 bash mock_cb/curl-smoke.sh
set -euo pipefail

BASE="${MOCK_CB_URL:-http://localhost:8000}"

echo "=== healthz ==="
curl -fsS "$BASE/healthz"; echo
# expected: {"status":"ok"}

echo ""
echo "=== verify (happy path — Jan Kowalski, 1988-07-21, last4=3476) ==="
curl -fsS -X POST "$BASE/verify" \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Jan","last_name":"Kowalski","dob":"1988-07-21","card_last4":"3476"}'; echo
# expected: {"verified":true,"customer_id":"CUST-000001","reason":null}

echo ""
echo "=== verify (negative — wrong DOB and card) ==="
curl -fsS -X POST "$BASE/verify" \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Jan","last_name":"Kowalski","dob":"1990-01-01","card_last4":"0000"}'; echo
# expected: {"verified":false,"customer_id":null,"reason":"Dane nie zgadzają się z naszymi zapisami."}

echo ""
echo "=== get_balance ==="
curl -fsS "$BASE/get_balance?customer_id=CUST-000001"; echo
# expected: {"customer_id":"CUST-000001","balance_pln":15634.97,"currency":"PLN","account_number":"PL61..."}

echo ""
echo "=== find_transaction (Zalando Lounge, 60 dni) ==="
curl -fsS "$BASE/find_transaction?customer_id=CUST-000001&merchant=Zalando%20Lounge&days=60"; echo
# expected: matches=[{transaction_id:TXN-20260324-001, amount_pln:540.01, booked_at:2026-03-24...}]

echo ""
echo "=== find_transaction (Biedronka — dystraktor, 7 dni) ==="
curl -fsS "$BASE/find_transaction?customer_id=CUST-000001&merchant=Biedronka&days=7"; echo
# expected: matches=[{transaction_id:TXN-20260407-002, amount_pln:87.43, ...}]

echo ""
echo "=== find_transaction (IKEA — brak, 30 dni) ==="
curl -fsS "$BASE/find_transaction?customer_id=CUST-000001&merchant=IKEA&days=30"; echo
# expected: matches=[]+

echo ""
echo "=== find_transaction (Zalando — 2 matche przez szerokie okno 200 dni) ==="
curl -fsS "$BASE/find_transaction?customer_id=CUST-000001&merchant=Zalando&days=200"; echo
# expected: matches zawiera TXN-20260324-001 (pierwszy, newest) i TXN-20251116-004 (drugi)

echo ""
echo "=== find_transaction (days=0 — walidacja 422) ==="
curl -sS -o /dev/null -w "%{http_code}\n" "$BASE/find_transaction?customer_id=CUST-000001&merchant=Zalando&days=0"
# expected: 422

echo ""
echo "=== rag_search (regulamin konta lokacyjnego — oprocentowanie) ==="
curl -fsS "$BASE/rag_search?doc=regulamin_konta_lokacyjnego.pdf&query=oprocentowanie"; echo
# expected: chunks contain source "Regulamin konta lokacyjnego Bank Demo, §3.1" and text with "7%"

echo ""
echo "=== rag_search (konto marzen — bonus) ==="
curl -fsS "$BASE/rag_search?doc=konto_marzen.pdf&query=bonus"; echo
# expected: chunks contain source "Oferta Konto Marzeń, str. 2" and text with "300 zł"

echo ""
echo "=== rag_search (nieistniejacy dokument — 404) ==="
curl -sS -o /dev/null -w "%{http_code}\n" "$BASE/rag_search?doc=nieistniejacy_dokument.pdf&query=test"
# expected: 404

echo ""
echo "=== send_offer ==="
curl -fsS -X POST "$BASE/send_offer" \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"CUST-000001","offer":"konto_marzen"}'; echo
# expected: {"status":"sent","offer":"konto_marzen","customer_id":"CUST-000001"}

echo ""
echo "All checks passed."

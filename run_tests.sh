#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Customer Support Agent — Automated Test Runner
# Runs all 6 required tests one by one with clear output
# ─────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     Customer Support Agent — All 6 Tests             ║"
echo "╚══════════════════════════════════════════════════════╝"

run_test() {
  local test_num=$1
  local test_name=$2
  local payload=$3

  echo ""
  echo "─────────────────────────────────────────────────────"
  echo "▶  TEST $test_num — $test_name"
  echo "─────────────────────────────────────────────────────"
  python3 -m uv run main.py "$payload"
  echo ""
  echo "✅ TEST $test_num COMPLETE"
  sleep 3
}

# Test 1 — Order Tracking
run_test 1 "Order Tracking" \
  '{"prompt": "Can you track my order ORD-001 and tell me its status?", "customer_id": "CUST-123", "session_id": "test-1"}'

# Test 2 — Refund Processing
run_test 2 "Refund Processing" \
  '{"prompt": "I want to return my Kindle Paperwhite for order ORD-002 and get a refund", "customer_id": "CUST-123", "session_id": "test-2"}'

# Test 3 — Knowledge Base (RAG)
run_test 3 "Knowledge Base RAG" \
  '{"prompt": "What are the benefits of the Platinum loyalty tier and what is the return policy?", "customer_id": "CUST-123", "session_id": "test-3"}'

# Test 4a — Long-Term Memory Session 1
run_test "4a" "Memory - Session 1 (Store)" \
  '{"prompt": "Hi I am Jane and I prefer concise responses from customer support", "customer_id": "CUST-123", "session_id": "session-A"}'

echo "⏳ Waiting 10 seconds for memory to be saved..."
sleep 10

# Test 4b — Long-Term Memory Session 2
run_test "4b" "Memory - Session 2 (Recall)" \
  '{"prompt": "Do you remember my name and my communication preference?", "customer_id": "CUST-123", "session_id": "session-B"}'

# Test 5 — Loyalty Discount Calculation
run_test 5 "Loyalty Discount Calculation" \
  '{"prompt": "I am a Gold tier member with 4250 loyalty points. Calculate my discount on a $150 standard order", "customer_id": "CUST-123", "session_id": "test-5"}'

# Test 6 — Browser Tool
run_test 6 "Browser Tool" \
  '{"prompt": "Go to https://www.amazon.com and tell me the page title", "customer_id": "CUST-123", "session_id": "test-6"}'

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     ALL 6 TESTS COMPLETE! Take screenshots now.      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

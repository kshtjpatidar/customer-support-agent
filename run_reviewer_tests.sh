#!/bin/bash
# ─────────────────────────────────────────────────────────────
# AWS Final Evidence Runner (No Deploy)
# ─────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════╗"
echo "║   Udacity Final Evidence — AgentCore Invoke Tests    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

echo "▶ STEP 1: Downloading latest fixed code..."
curl -s -H "Cache-Control: no-cache" -H "Accept: application/vnd.github.v3.raw" \
  https://api.github.com/repos/kshtjpatidar/customer-support-agent/contents/main.py -o main.py
echo "✅ Code downloaded."

echo ""
echo "▶ STEP 2: Browser Tool Test"
echo "Command: uv run agentcore invoke '{\"prompt\": \"Go to https://www.udacity.com and tell me the page title.\", \"customer_id\": \"CUST-123\", \"session_id\": \"browser-test\"}'"
uv run agentcore invoke '{"prompt": "Go to https://www.udacity.com and tell me the page title.", "customer_id": "CUST-123", "session_id": "browser-test"}'
echo ""
echo "📸 SCREENSHOT NOW! (Browser Tool Evidence)"
echo "Press Enter to continue to the Memory tests..."
read -p ""

echo ""
echo "▶ STEP 3: Memory Test - Session A (Store Jane)"
echo "Command: uv run agentcore invoke '{\"prompt\": \"Hi, I am Jane. I prefer concise responses.\", \"customer_id\": \"CUST-JANE\", \"session_id\": \"s-A\"}'"
uv run agentcore invoke '{"prompt": "Hi, I am Jane. I prefer concise responses.", "customer_id": "CUST-JANE", "session_id": "s-A"}'
echo ""
echo "⏳ Waiting 30 seconds for AWS Bedrock to index the memory..."
sleep 30

echo ""
echo "▶ STEP 4: Memory Test - Session B (Recall Jane)"
echo "Command: uv run agentcore invoke '{\"prompt\": \"Do you remember my name and communication preference?\", \"customer_id\": \"CUST-JANE\", \"session_id\": \"s-B\"}'"
uv run agentcore invoke '{"prompt": "Do you remember my name and communication preference?", "customer_id": "CUST-JANE", "session_id": "s-B"}'
echo ""
echo "📸 SCREENSHOT NOW! (Memory Recall Evidence)"
echo ""
echo "🎉 YOU ARE DONE! Submit these two new screenshots to Udacity!"

#!/bin/bash
# ─────────────────────────────────────────────────────────────
# AWS Final Evidence Runner 
# ─────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════╗"
echo "║   Udacity Final Evidence — AWS Deployment & Tests    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

echo "▶ STEP 1: Downloading latest fixed code..."
curl -s -H "Cache-Control: no-cache" -H "Accept: application/vnd.github.v3.raw" \
  https://api.github.com/repos/kshtjpatidar/customer-support-agent/contents/main.py -o main.py
echo "✅ Code downloaded."

echo ""
echo "▶ STEP 2: Deploying to AWS (This takes a minute)..."
export PATH="$HOME/.local/bin:$PATH"
uv run agentcore deploy
if [ $? -ne 0 ]; then
    echo "❌ Deployment failed! Please check the error above."
    exit 1
fi
echo "✅ Deployment successful!"

echo ""
echo "▶ STEP 3: Browser Tool Test"
echo "Command: uv run agentcore invoke '{\"prompt\": \"Go to https://www.udacity.com and tell me the page title.\"}'"
uv run agentcore invoke '{"prompt": "Go to https://www.udacity.com and tell me the page title."}'
echo ""
echo "📸 SCREENSHOT NOW! (Browser Tool Evidence)"
echo "Press Enter to continue to the Memory tests..."
read -p ""

echo ""
echo "▶ STEP 4: Memory Test - Session A (Store Jane)"
echo "Command: uv run agentcore invoke '{\"prompt\": \"Hi, I am Jane. I prefer concise responses.\", \"customer_id\": \"CUST-JANE\", \"session_id\": \"s-A\"}'"
uv run agentcore invoke '{"prompt": "Hi, I am Jane. I prefer concise responses.", "customer_id": "CUST-JANE", "session_id": "s-A"}'
echo ""
echo "⏳ Waiting 30 seconds for AWS Bedrock to index the memory..."
sleep 30

echo ""
echo "▶ STEP 5: Memory Test - Session B (Recall Jane)"
echo "Command: uv run agentcore invoke '{\"prompt\": \"Do you remember my name and communication preference?\", \"customer_id\": \"CUST-JANE\", \"session_id\": \"s-B\"}'"
uv run agentcore invoke '{"prompt": "Do you remember my name and communication preference?", "customer_id": "CUST-JANE", "session_id": "s-B"}'
echo ""
echo "📸 SCREENSHOT NOW! (Memory Recall Evidence)"
echo ""
echo "🎉 YOU ARE DONE! Submit these two new screenshots to Udacity!"

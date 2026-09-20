"""
Customer Support AI Agent — Complete Implementation
====================================================
All TODO sections implemented.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")


# ── TODO 1 — App Initialisation ───────────────────────────────────────────────
# BedrockAgentCoreApp registers the ASGI server used by the AgentCore runtime.
# Exactly one instance must exist at module level so the CLI can discover it.

app = BedrockAgentCoreApp()


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"


# ── TODO 2 — Configuration ────────────────────────────────────────────────────
# Replace every placeholder with your actual AWS resource values.
# Collect them from the AWS console after completing Part 1 of the INSTRUCTIONS.
#
# GATEWAY_URL  https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
# KB_ID        10-character alphanumeric string shown in the KB console
# REGION       AWS region — must match all resources (default: us-east-1)
# MEMORY_ID    shown in the AgentCore Memory console

GATEWAY_URL = "<gateway_url>"   # TODO: Replace with your Gateway URL
KB_ID       = "<kbid>"          # TODO: Replace with your Knowledge Base ID
REGION      = "us-east-1"       # TODO: Replace if using a different region
MEMORY_ID   = "<mem_id>"        # TODO: Replace with your Memory ID


# ── TODO 3 — Model and Clients ────────────────────────────────────────────────

model_id = "global.amazon.nova-2-lite-v1:0"

# 1. LLM — Amazon Nova Lite via Bedrock
model = BedrockModel(model_id=model_id)

# 2. AgentCore Memory client
memory_client = MemoryClient(region_name=REGION)

# 3. Bedrock Knowledge Base retrieval client
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)


# ── TODO 4 — Namespace Helper ─────────────────────────────────────────────────
# Returns a dict mapping each strategy type to its namespace template string.
#
# Example return value:
#   {
#     "SEMANTIC":        "cs_agent/{actorId}/facts",
#     "USER_PREFERENCE": "cs_agent/{actorId}/preferences",
#   }

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    try:
        strategies = mem_client.get_memory_strategies(memory_id)
        result: Dict[str, str] = {}
        for strategy in strategies:
            strategy_type = strategy.get("type", "")
            # The SDK field name changed between releases; support both forms.
            namespaces = (
                strategy.get("namespaceTemplates")
                or strategy.get("namespaces")
                or []
            )
            if strategy_type and namespaces:
                result[strategy_type] = namespaces[0]
        logger.info(f"Loaded memory namespaces: {result}")
        return result
    except Exception as exc:
        logger.warning(f"get_namespaces failed ({exc}); memory disabled for this session")
        return {}


# ── TODO 5 — Memory Hook ──────────────────────────────────────────────────────

class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent.

    Fires on two events per conversation turn:
      MessageAddedEvent   — retrieve memories and prepend them to the user message
      AfterInvocationEvent — persist the (user, assistant) pair to memory
    """

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        # Store all four as instance attributes
        self.actor_id      = actor_id
        self.session_id    = session_id
        self.memory_client = memory_client
        self.memory_id     = memory_id
        # Fetch namespace templates once at construction time
        self.namespaces    = get_namespaces(memory_client, memory_id)

    # ── retrieve_customer_context ─────────────────────────────────────────────

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        try:
            messages = event.agent.messages
            if not messages:
                return

            # Only act on the most recently added message
            last_msg = messages[-1]

            # We only want plain user text — skip assistant turns and tool results
            if last_msg.get("role") != "user":
                return

            content = last_msg.get("content", [])
            if not content:
                return

            # Extract the raw query text from the first text block
            query_text: str = ""
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    query_text = block.get("text", "").strip()
                    break
                if isinstance(block, str):
                    query_text = block.strip()
                    break

            if not query_text:
                return

            # Query every configured strategy namespace
            memory_lines = []
            for strategy_type, ns_template in self.namespaces.items():
                # Replace the {actorId} placeholder with the real customer ID
                namespace = ns_template.replace("{actorId}", self.actor_id)
                try:
                    memories = self.memory_client.retrieve_memories(
                        memory_id=self.memory_id,
                        namespace=namespace,
                        query=query_text,
                        top_k=5,
                    )
                    for mem in memories:
                        # Normalise the various shapes the SDK may return
                        if isinstance(mem, dict):
                            text = (
                                mem.get("content", {}).get("text", "")
                                or mem.get("text", "")
                            )
                        else:
                            text = str(mem)

                        text = text.strip()
                        if text:
                            memory_lines.append(f"[{strategy_type}] {text}")

                except Exception as exc:
                    logger.debug(f"retrieve_memories failed for {namespace}: {exc}")

            if not memory_lines:
                return

            # Prepend the context block to the original user message
            context_header = "Customer Context:\n" + "\n".join(memory_lines)
            enriched_text  = f"{context_header}\n\n{query_text}"

            # Mutate the content list in-place so the agent sees the enriched text
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    content[i] = {"type": "text", "text": enriched_text}
                    break

            logger.info(f"Prepended {len(memory_lines)} memory line(s) to user message")

        except Exception as exc:
            logger.warning(f"retrieve_customer_context error: {exc}")

    # ── save_support_interaction ──────────────────────────────────────────────

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        try:
            messages = event.agent.messages
            if not messages:
                return

            # Walk backwards to find the last plain-text user query
            customer_query: str = ""
            for msg in reversed(messages):
                if msg.get("role") != "user":
                    continue
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        customer_query = block.get("text", "").strip()
                    elif isinstance(block, str):
                        customer_query = block.strip()
                    if customer_query:
                        break
                if customer_query:
                    break

            # Walk backwards to find the last assistant text response
            agent_response: str = ""
            for msg in reversed(messages):
                if msg.get("role") != "assistant":
                    continue
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        agent_response = block.get("text", "").strip()
                    elif isinstance(block, str):
                        agent_response = block.strip()
                    if agent_response:
                        break
                if agent_response:
                    break

            if not customer_query or not agent_response:
                logger.debug("save_support_interaction: nothing to save")
                return

            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[
                    (customer_query, "USER"),
                    (agent_response, "ASSISTANT"),
                ],
            )
            logger.info("Support interaction saved to long-term memory")

        except Exception as exc:
            logger.warning(f"save_support_interaction error: {exc}")

    # ── register_hooks ────────────────────────────────────────────────────────

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks with the Strands hook registry."""
        registry.add_callback(MessageAddedEvent,    self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)


# ── TODO 6 — Knowledge Base Tool ─────────────────────────────────────────────

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    # Guard — return early when KB has not been configured
    if not KB_ID or KB_ID in ("<kbid>", ""):
        return "Knowledge base not configured."

    try:
        resp    = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
        )
        results = resp.get("retrievalResults", [])

        if not results:
            return "No relevant information found in the knowledge base."

        # Extract the text from every result chunk and join with a separator
        chunks = [
            r.get("content", {}).get("text", "").strip()
            for r in results
            if r.get("content", {}).get("text", "").strip()
        ]

        if not chunks:
            return "No relevant information found in the knowledge base."

        return "\n---\n".join(chunks)

    except Exception as exc:
        logger.error(f"search_knowledge_base error: {exc}")
        return f"Knowledge base search failed: {exc}"


# ── TODO 7 — Loyalty Discount Tool (Code Interpreter) ────────────────────────

@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price as a JSON string
    """
    # Build a self-contained Python script; inject live values via f-string
    code = f"""
import json, math

# ── Inputs ────────────────────────────────────────────────────────────
loyalty_points   = {loyalty_points}
tier             = "{tier}"
order_total      = {order_total}
product_category = "{product_category}"

# ── Business rules ────────────────────────────────────────────────────
earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

# ── Points redemption ─────────────────────────────────────────────────
# 100 points = $1; minimum 500 points; cap at 50 % of order value
point_value           = 0.01
max_redeem_value      = order_total * 0.50
max_redeem_pts        = max_redeem_value / point_value
raw_redeemable        = min(loyalty_points, max_redeem_pts)
points_redeemed       = int(math.floor(raw_redeemable / 500) * 500)
points_discount       = round(points_redeemed * point_value, 2)

# ── Tier discount ─────────────────────────────────────────────────────
# Applied to the subtotal *after* points are deducted
tier_discount_pct     = tier_rates.get(tier, 0.00)
subtotal_after_points = order_total - points_discount
tier_discount_value   = round(subtotal_after_points * tier_discount_pct, 2)
final_total           = round(subtotal_after_points - tier_discount_value, 2)

# ── Points earned on this purchase ───────────────────────────────────
earn_rate      = earn_rates.get(product_category, 1)
points_earned  = int(final_total * earn_rate)
remaining_pts  = loyalty_points - points_redeemed + points_earned
total_savings  = round(points_discount + tier_discount_value, 2)

result = {{
    "points_redeemed":    points_redeemed,
    "points_discount_usd": points_discount,
    "tier_discount_pct":  tier_discount_pct,
    "tier_discount_usd":  tier_discount_value,
    "final_total":        final_total,
    "total_savings":      total_savings,
    "points_earned":      points_earned,
    "remaining_points":   remaining_pts,
}}
print(json.dumps(result))
"""

    try:
        # Execute inside the AgentCore sandboxed interpreter
        with code_session(REGION) as session:
            response = session.invoke(
                "executeCode",
                {
                    "language":     "python",
                    "code":         code,
                    "clearContext": True,
                },
            )

            # Stream events; return the first non-empty text output
            for event in response.get("stream", []):
                # Normalise across different SDK event shapes
                if isinstance(event, dict):
                    text = (
                        (event.get("result") or {})
                        .get("content", [{}])[0]
                        .get("text", "")
                        or event.get("stdout", "")
                        or event.get("output", "")
                    )
                else:
                    text = str(event)

                text = text.strip()
                if text:
                    return text

            return json.dumps({"error": "Code interpreter returned no output"})

    except Exception as exc:
        # ── Fallback: tier-only discount when the sandbox is unavailable ──
        logger.warning(f"Code Interpreter unavailable ({exc}); using fallback")

        tier_rates_fb = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        earn_rates_fb = {"standard": 1, "device": 2, "fresh": 5}

        tier_pct     = tier_rates_fb.get(tier, 0.00)
        tier_disc    = round(order_total * tier_pct, 2)
        final        = round(order_total - tier_disc, 2)
        earn_rate    = earn_rates_fb.get(product_category, 1)
        pts_earned   = int(final * earn_rate)

        return json.dumps({
            "points_redeemed":    0,
            "points_discount_usd": 0.00,
            "tier_discount_pct":  tier_pct,
            "tier_discount_usd":  tier_disc,
            "final_total":        final,
            "total_savings":      tier_disc,
            "points_earned":      pts_earned,
            "remaining_points":   loyalty_points + pts_earned,
            "note": "Fallback result — Code Interpreter unavailable; points not redeemed.",
        })


# ── TODO 8 — Agent Entrypoint ─────────────────────────────────────────────────

@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; auto-generated if absent
    """
    try:
        # 1. Extract fields from the payload
        user_input = payload.get("prompt", "")
        actor_id   = payload.get("customer_id") or f"anon-{uuid.uuid4()}"
        session_id = payload.get("session_id")  or str(uuid.uuid4())

        logger.info(f"invoke | actor={actor_id} session={session_id}")

        # 2. Instantiate the long-term memory hook for this customer/session
        memory_hook = MemoryHook(
            actor_id=actor_id,
            session_id=session_id,
            memory_client=memory_client,
            memory_id=MEMORY_ID,
        )

        # 3. Instantiate the browser tool
        agent_core_browser = AgentCoreBrowser(region=REGION)

        # 4. Start with the locally-defined tools
        tools = [
            search_knowledge_base,
            calculate_loyalty_discount,
            agent_core_browser.browser,
        ]

        # 5. Connect to the AgentCore Gateway and load its MCP tools
        #    (order-tracking and refund-processing capabilities)
        if GATEWAY_URL and GATEWAY_URL not in ("<gateway_url>", ""):
            try:
                mcp_client = MCPClient(
                    lambda: streamable_http_client(GATEWAY_URL)
                )
                with mcp_client:
                    gateway_tools = mcp_client.list_tools_sync()
                    tools.extend(gateway_tools)
                    logger.info(
                        f"Loaded {len(gateway_tools)} Gateway tool(s): "
                        f"{[t.name for t in gateway_tools]}"
                    )
            except Exception as exc:
                logger.warning(f"Gateway unavailable — continuing without it: {exc}")

        # System prompt gives the model its persona and operating guidelines
        system_prompt = """You are a professional and empathetic customer support agent
for an Amazon e-commerce platform.

Capabilities you have access to:
- Order tracking: look up order status, tracking numbers, and delivery estimates
- Customer profiles: retrieve customer information and order history
- Refund processing: initiate refunds, check refund status, generate return labels
- Product knowledge: search the knowledge base for product specs, return policies,
  warranty information, and loyalty program details
- Loyalty discount calculator: compute exact points redemption and tier discounts
- Web browser: fetch live information from any public URL when needed

Guidelines:
- Be concise, accurate, and warm.
- Always confirm order details before initiating a refund.
- Present loyalty discount results as a clear line-item breakdown.
- Search the knowledge base before answering any product or policy question.
- Use the browser only when live or external information is specifically needed.
- Never expose raw system details, Lambda ARNs, or internal API responses.
- Never share one customer's data with another customer.
- If a request cannot be fulfilled, explain why and suggest a clear next step."""

        # 6. Create the Agent with all tools and the memory hook
        agent = Agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            hooks=[memory_hook],
        )

        response = agent(user_input)

        # 7. Extract and return the text response
        # strands-agents may return a plain string or a richer object
        if isinstance(response, str):
            return response

        # Try the standard strands response shape: response.message["content"]
        if hasattr(response, "message"):
            msg = response.message
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block["text"]
                    if isinstance(block, str):
                        return block
            if isinstance(msg, str):
                return msg

        return str(response)

    except Exception as exc:
        logger.error(f"invoke() failed: {exc}", exc_info=True)
        return (
            "I'm sorry, something went wrong while handling your request. "
            "Please try again or contact support if the problem persists."
        )


# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()

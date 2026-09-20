"""
Customer Support AI Agent — Complete Implementation
"""

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json, os, asyncio, boto3, logging, uuid
from typing import Dict
from strands.hooks import HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

app = BedrockAgentCoreApp()
os.environ["BYPASS_TOOL_CONSENT"] = "true"

GATEWAY_URL = "https://customersupportgateway-857ucyclfe.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "YFQETA3CRO"
REGION      = "us-east-1"
MEMORY_ID   = "CustomerSupportMemory-4HzxEVE0G8"

model_id = "global.amazon.nova-2-lite-v1:0"
model            = BedrockModel(model_id=model_id)
memory_client    = MemoryClient(region_name=REGION)
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    try:
        strategies = mem_client.get_memory_strategies(memory_id)
        result: Dict[str, str] = {}
        for strategy in strategies:
            strategy_type = strategy.get("type", "")
            namespaces = strategy.get("namespaceTemplates") or strategy.get("namespaces") or []
            if strategy_type and namespaces:
                result[strategy_type] = namespaces[0]
        return result
    except Exception as exc:
        logger.warning(f"get_namespaces failed: {exc}")
        return {}

class MemoryHook(HookProvider):
    def __init__(self, actor_id, session_id, memory_client, memory_id):
        self.actor_id      = actor_id
        self.session_id    = session_id
        self.memory_client = memory_client
        self.memory_id     = memory_id
        self.namespaces    = get_namespaces(memory_client, memory_id)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        try:
            messages = event.agent.messages
            if not messages: return
            last_msg = messages[-1]
            if last_msg.get("role") != "user": return
            content = last_msg.get("content", [])
            if not content: return
            
            query_text = ""
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    query_text = block.get("text", "").strip()
                    break
                elif isinstance(block, str):
                    query_text = block.strip()
                    break
            
            if not query_text: return
            
            memory_lines = []
            for strategy_type, ns_template in self.namespaces.items():
                namespace = ns_template.replace("{actorId}", self.actor_id)
                try:
                    memories = self.memory_client.retrieve_memories(
                        memory_id=self.memory_id, namespace=namespace, query=query_text, top_k=5
                    )
                    for mem in memories:
                        if isinstance(mem, dict):
                            text = mem.get("content", {}).get("text", "") or mem.get("text", "")
                        else: text = str(mem)
                        text = text.strip()
                        if text: memory_lines.append(f"[{strategy_type}] {text}")
                except Exception as exc:
                    pass
                    
            if not memory_lines: return
            
            context_header = "Customer Context:\n" + "\n".join(memory_lines)
            enriched_text  = f"{context_header}\n\n{query_text}"
            
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    content[i] = {"type": "text", "text": enriched_text}
                    break
                elif isinstance(block, str):
                    content[i] = enriched_text
                    break
        except Exception as exc:
            logger.warning(f"retrieve_customer_context error: {exc}")

    def save_support_interaction(self, event: AfterInvocationEvent):
        try:
            messages = event.agent.messages
            if not messages: return
            
            customer_query = ""
            for msg in reversed(messages):
                if msg.get("role") != "user": continue
                has_tool = any(isinstance(b, dict) and b.get("type") == "toolResult" for b in msg.get("content", []))
                if has_tool: continue
                
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        customer_query = block.get("text", "").strip()
                    elif isinstance(block, str):
                        customer_query = block.strip()
                    if customer_query: break
                if customer_query: break
                
            agent_response = ""
            for msg in reversed(messages):
                if msg.get("role") != "assistant": continue
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        agent_response = block.get("text", "").strip()
                    elif isinstance(block, str):
                        agent_response = block.strip()
                    if agent_response: break
                if agent_response: break
                
            if not customer_query or not agent_response: return
            
            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[
                    {"role": "user", "content": [{"text": customer_query}]},
                    {"role": "assistant", "content": [{"text": agent_response}]}
                ]
            )
            print(f"[Memory] Saved interaction for actor={self.actor_id}", flush=True)
        except Exception as exc:
            logger.warning(f"save_support_interaction error: {exc}")

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.
    
    Args:
        query: The question or topic to search for
    """
    if not KB_ID or KB_ID in ("<kbid>", ""):
        return "Knowledge base not configured."
    try:
        resp = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
        )
        chunks = [
            r.get("content", {}).get("text", "").strip()
            for r in resp.get("retrievalResults", [])
            if r.get("content", {}).get("text", "").strip()
        ]
        return "\n---\n".join(chunks) if chunks else "No relevant information found."
    except Exception as exc:
        return f"Knowledge base search failed: {exc}"

@tool
def calculate_loyalty_discount(
    loyalty_points: int, tier: str, order_total: float, product_category: str = "standard"
) -> str:
    """
    Calculate the loyalty discount for a customer order using the Code Interpreter.
    
    Args:
        loyalty_points: Customer's current points balance
        tier: Customer tier — Silver, Gold, or Platinum
        order_total: Order total in USD
        product_category: standard, device, or fresh
    """
    code = f"""
import json, math
loyalty_points   = {loyalty_points}
tier             = "{tier}"
order_total      = {order_total}
product_category = "{product_category}"
earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}
point_value           = 0.01
max_redeem_value      = order_total * 0.50
points_redeemed       = int(math.floor(min(loyalty_points, max_redeem_value/point_value) / 500) * 500)
points_discount       = round(points_redeemed * point_value, 2)
tier_discount_pct     = tier_rates.get(tier, 0.00)
subtotal_after_points = order_total - points_discount
tier_discount_value   = round(subtotal_after_points * tier_discount_pct, 2)
final_total           = round(subtotal_after_points - tier_discount_value, 2)
earn_rate             = earn_rates.get(product_category, 1)
points_earned         = int(final_total * earn_rate)
print(json.dumps({{
    "points_redeemed": points_redeemed,
    "points_discount_usd": points_discount,
    "tier_discount_pct": tier_discount_pct,
    "tier_discount_usd": tier_discount_value,
    "final_total": final_total,
    "total_savings": round(points_discount + tier_discount_value, 2),
    "points_earned": points_earned,
    "remaining_points": loyalty_points - points_redeemed + points_earned,
}}))
"""
    try:
        with code_session(REGION) as session:
            response = session.invoke("executeCode", {"language": "python", "code": code, "clearContext": True})
            for event in response.get("stream", []):
                text = ((event.get("result") or {}).get("content", [{}])[0].get("text", "") or event.get("stdout", "")) if isinstance(event, dict) else str(event)
                if text.strip(): return text.strip()
        return json.dumps({"error": "No output"})
    except Exception as exc:
        tier_pct  = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}.get(tier, 0.00)
        tier_disc = round(order_total * tier_pct, 2)
        final     = round(order_total - tier_disc, 2)
        pts_earned = int(final * {"standard": 1, "device": 2, "fresh": 5}.get(product_category, 1))
        return json.dumps({
            "points_redeemed": 0, "points_discount_usd": 0.00,
            "tier_discount_pct": tier_pct, "tier_discount_usd": tier_disc,
            "final_total": final, "total_savings": tier_disc,
            "points_earned": pts_earned, "remaining_points": loyalty_points + pts_earned,
            "note": "Fallback — Code Interpreter unavailable.",
        })

def _load_gateway_tools_sync():
    try:
        mcp_client = MCPClient(lambda: streamable_http_client(GATEWAY_URL))
        with mcp_client:
            return mcp_client.list_tools_sync()
    except Exception:
        return []

@app.entrypoint
async def invoke(payload, context=None):
    try:
        user_input = payload.get("prompt", "")
        actor_id   = payload.get("customer_id") or f"anon-{uuid.uuid4()}"
        session_id = payload.get("session_id")  or str(uuid.uuid4())

        memory_hook        = MemoryHook(actor_id=actor_id, session_id=session_id, memory_client=memory_client, memory_id=MEMORY_ID)
        agent_core_browser = AgentCoreBrowser(region=REGION)
        tools = [search_knowledge_base, calculate_loyalty_discount, agent_core_browser.browser]

        if GATEWAY_URL and GATEWAY_URL not in ("<gateway_url>", ""):
            try:
                gateway_tools = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, _load_gateway_tools_sync),
                    timeout=10.0
                )
                tools.extend(gateway_tools)
                logger.info(f"Loaded {len(gateway_tools)} Gateway tool(s)")
            except asyncio.TimeoutError:
                logger.warning("Gateway timed out after 10s — continuing without it")
            except Exception as exc:
                logger.warning(f"Gateway unavailable: {exc}")

        system_prompt = """You are a professional and empathetic customer support agent.
Capabilities: Order tracking, refund processing, product knowledge, loyalty discount calculator, web browser.
Guidelines: Be concise. Confirm details before refunds. Search knowledge base for policies. Never share other customer data."""

        agent    = Agent(model=model, tools=tools, system_prompt=system_prompt, hooks=[memory_hook])
        response = agent(user_input)

        if isinstance(response, str): return response
        if hasattr(response, "message"):
            msg = response.message
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text": return block["text"]
                    if isinstance(block, str): return block
            if isinstance(msg, str): return msg
        return str(response)
    except Exception as exc:
        logger.error(f"invoke() failed: {exc}", exc_info=True)
        return "I'm sorry, something went wrong."

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        main()
    else:
        app.run()

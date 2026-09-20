# Project Reflection — Customer Support AI Agent

## Design Decision: MemoryHook with Dual-Strategy Namespace Retrieval

One specific design choice I made was in the `MemoryHook` class, particularly in how
`retrieve_customer_context` retrieves memories before each user turn. Rather than
hard-coding a single namespace, I designed `get_namespaces()` to call
`get_memory_strategies()` at startup and return a live map of all configured strategies
(e.g., `SEMANTIC → cs_agent/{actorId}/facts` and `USER_PREFERENCE → cs_agent/{actorId}/preferences`).
This means the hook automatically adapts to whatever strategies were provisioned in the
AgentCore Memory console, making it portable and forward-compatible. The tradeoff is a
small startup latency hit, but since namespaces are fetched once per session and cached as
`self.namespaces`, this is negligible in practice. The alternative — hard-coding namespace
strings — would have been brittle and required code changes any time a Memory strategy was
added, renamed, or restructured.

## Challenge Encountered: Memory SDK API Field Name Variance

The most concrete challenge I encountered was reconciling the field name differences between
versions of the `bedrock-agentcore` SDK. The SDK documentation and some examples used
`"namespaces"` as the field name on each strategy object, while newer releases and some
service API responses returned `"namespaceTemplates"` instead. A naïve implementation that
only checked one field caused a silent empty-dict return, which meant memory retrieval never
ran and cross-session recall silently failed during testing. I resolved this by adding a
defensive fallback: `strategy.get("namespaceTemplates") or strategy.get("namespaces", [])`,
which checks the new field first and gracefully falls back to the legacy field. I verified
the fix by asserting that `self.namespaces` was non-empty after `MemoryHook.__init__()` and
tracing the retrieval calls in the logs.

## Production Consideration: Cost and LLM Provider Resilience

The most pressing production concern for an agent of this type is **cost and availability
of the LLM provider**. Because every customer turn involves at least one model invocation —
and often two or three when tool calls are involved — the cost per session scales directly
with model verbosity and tool chain depth. In a production system I would address this
through: (a) a per-session token budget enforced in the system prompt and checked
pre-invocation; (b) routing simple FAQ queries to a lighter model tier (e.g., Nova Lite
versus a larger model) identified via a classifier; and (c) a provider failover pattern
where a secondary LLM provider is configured so the agent degrades gracefully rather than
returning an error if the primary provider is experiencing an outage. The fallback path I
implemented in `calculate_loyalty_discount()` — which computes a tier-only discount when the
Code Interpreter is unavailable — demonstrates the same principle applied at the tool level:
always prefer graceful degradation over silent failure.

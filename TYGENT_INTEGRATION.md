# Tygent Integration

This project uses [Tygent](https://github.com/OpenPipe/tygent) to schedule agents asynchronously and run their tasks in a DAG. The integration occurs in two places:

1. **Orchestrator (`orchestrator.py`)**
   - If `use_tygent` is enabled when creating `TaskOrchestrator`, the orchestrator uses `MultiAgentManager` to run multiple agents concurrently. Each agent is wrapped in a tiny class with an `execute` coroutine that calls `run_agent_async`.
   - When Tygent execution fails or is disabled, the orchestrator falls back to a thread pool so functionality does not break.
   - Progress updates and aggregation work the same regardless of the execution strategy.

2. **Agent (`agent.py`)**
   - Each `OpenRouterAgent` exposes a `run_async` method that builds a Tygent `DAG` representing the agent plan.
   - The DAG issues web search nodes in parallel and then summarizes the results with the LLM using Tygent's `Scheduler`.
   - This allows individual agents to benefit from asynchronous execution while still supporting the synchronous `run` method used by the thread‑pool fallback.

The `benchmark.py` script demonstrates the performance difference by running example prompts with Tygent enabled and disabled. It shows how asynchronous execution can speed up workflows that rely on parallel web search.

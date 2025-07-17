import json
import yaml
import asyncio
from typing import Dict, Any, List
from openai import OpenAI, AsyncOpenAI
from tools import discover_tools
from tygent.dag import DAG
from tygent.nodes import Node
from tygent.scheduler import Scheduler

class OpenRouterAgent:
    def __init__(self, config_path="config.yaml", silent=False):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Silent mode for orchestrator (suppresses debug output)
        self.silent = silent
        
        # Initialize OpenAI clients (sync and async) with OpenRouter
        self.client = OpenAI(
            base_url=self.config['openrouter']['base_url'],
            api_key=self.config['openrouter']['api_key']
        )
        self.async_client = AsyncOpenAI(
            base_url=self.config['openrouter']['base_url'],
            api_key=self.config['openrouter']['api_key']
        )
        
        # Discover tools dynamically
        self.discovered_tools = discover_tools(self.config, silent=self.silent)
        
        # Build OpenRouter tools array
        self.tools = [tool.to_openrouter_schema() for tool in self.discovered_tools.values()]
        
        # Build tool mapping
        self.tool_mapping = {name: tool.execute for name, tool in self.discovered_tools.items()}
    
    
    def call_llm(self, messages):
        """Make OpenRouter API call with tools"""
        try:
            response = self.client.chat.completions.create(
                model=self.config['openrouter']['model'],
                messages=messages,
                tools=self.tools
            )
            return response
        except Exception as e:
            raise Exception(f"LLM call failed: {str(e)}")

    async def generate_search_queries(self, user_input: str) -> List[str]:
        """Use the async client to generate web search queries for a task."""
        prompt = (
            "You are a planning assistant. Generate 3 concise web search queries "
            "that would help answer the following question. Return ONLY a JSON "
            "array of strings.\nQuestion: " + user_input
        )
        messages = [
            {"role": "system", "content": "You generate search queries."},
            {"role": "user", "content": prompt},
        ]
        try:
            resp = await self.async_client.chat.completions.create(
                model=self.config["openrouter"]["model"],
                messages=messages,
            )
            content = resp.choices[0].message.content
            return json.loads(content)
        except Exception:
            return [user_input]
    
    def handle_tool_call(self, tool_call):
        """Handle a tool call and return the result message"""
        try:
            # Extract tool name and arguments
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            # Call appropriate tool from tool_mapping
            if tool_name in self.tool_mapping:
                tool_result = self.tool_mapping[tool_name](**tool_args)
            else:
                tool_result = {"error": f"Unknown tool: {tool_name}"}
            
            # Return tool result message
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(tool_result)
            }
        
        except Exception as e:
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps({"error": f"Tool execution failed: {str(e)}"})
            }
    
    def run(self, user_input: str):
        """Run the agent with user input and return FULL conversation content"""
        # Initialize messages with system prompt and user input
        messages = [
            {
                "role": "system",
                "content": self.config['system_prompt']
            },
            {
                "role": "user",
                "content": user_input
            }
        ]
        
        # Track all assistant responses for full content capture
        full_response_content = []
        
        # Implement agentic loop from OpenRouter docs
        max_iterations = self.config.get('agent', {}).get('max_iterations', 10)
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            if not self.silent:
                print(f"🔄 Agent iteration {iteration}/{max_iterations}")
            
            # Call LLM
            response = self.call_llm(messages)
            
            # Add the response to messages
            assistant_message = response.choices[0].message
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            })
            
            # Capture assistant content for full response
            if assistant_message.content:
                full_response_content.append(assistant_message.content)
            
            # Check if there are tool calls
            if assistant_message.tool_calls:
                if not self.silent:
                    print(f"🔧 Agent making {len(assistant_message.tool_calls)} tool call(s)")
                # Handle each tool call
                task_completed = False
                for tool_call in assistant_message.tool_calls:
                    if not self.silent:
                        print(f"   📞 Calling tool: {tool_call.function.name}")
                    tool_result = self.handle_tool_call(tool_call)
                    messages.append(tool_result)
                    
                    # Check if this was the task completion tool
                    if tool_call.function.name == "mark_task_complete":
                        task_completed = True
                        if not self.silent:
                            print("✅ Task completion tool called - exiting loop")
                        # Return FULL conversation content, not just completion message
                        return "\n\n".join(full_response_content)
                
                # If task was completed, we already returned above
                if task_completed:
                    return "\n\n".join(full_response_content)
            else:
                if not self.silent:
                    print("💭 Agent responded without tool calls - continuing loop")
            
            # Continue the loop regardless of whether there were tool calls or not
        
        # If max iterations reached, return whatever content we gathered
        return "\n\n".join(full_response_content) if full_response_content else "Maximum iterations reached. The agent may be stuck in a loop."

    async def run_async(self, user_input: str) -> str:
        """Run the agent using a Tygent DAG with real async execution."""

        queries = await self.generate_search_queries(user_input)

        dag = DAG("agent_plan")
        search_nodes = []

        class SearchNode(Node):
            def __init__(self, agent: "OpenRouterAgent", name: str, query: str) -> None:
                super().__init__(name)
                self.agent = agent
                self.query = query

            async def execute(self, _inputs: Dict[str, Any]) -> list:
                tool = self.agent.discovered_tools.get("search_web")
                return await asyncio.to_thread(
                    tool.execute,
                    query=self.query,
                    max_results=self.agent.config["search"].get("max_results", 5),
                )

        for idx, q in enumerate(queries):
            node_name = f"search_{idx+1}"
            dag.add_node(SearchNode(self, node_name, q))
            search_nodes.append(node_name)

        class SummarizeNode(Node):
            def __init__(self, agent: "OpenRouterAgent") -> None:
                super().__init__("summarize")
                self.agent = agent

            async def execute(self, inputs: Dict[str, Any]) -> str:
                combined = json.dumps(inputs)
                messages = [
                    {"role": "system", "content": self.agent.config["system_prompt"]},
                    {
                        "role": "user",
                        "content": (
                            "Use these search results to answer the question: "
                            + user_input
                            + "\n" + combined
                        ),
                    },
                ]
                resp = await self.agent.async_client.chat.completions.create(
                    model=self.agent.config["openrouter"]["model"],
                    messages=messages,
                )
                return resp.choices[0].message.content

        dag.add_node(SummarizeNode(self))
        for name in search_nodes:
            dag.add_edge(name, "summarize")

        scheduler = Scheduler(dag)
        result = await scheduler.execute({})
        return result["results"]["summarize"]

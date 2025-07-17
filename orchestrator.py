import json
import yaml
import time
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
from agent import OpenRouterAgent
from tygent.multi_agent import MultiAgentManager

class TaskOrchestrator:
    def __init__(self, config_path="config.yaml", silent=False, use_tygent=True):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.num_agents = self.config['orchestrator']['parallel_agents']
        self.task_timeout = self.config['orchestrator']['task_timeout']
        self.aggregation_strategy = self.config['orchestrator']['aggregation_strategy']
        self.silent = silent
        self.use_tygent = use_tygent
        
        # Track agent progress
        self.agent_progress = {}
        self.agent_results = {}
        self.progress_lock = threading.Lock()
    
    def decompose_task(self, user_input: str, num_agents: int) -> List[str]:
        """Use AI to dynamically generate different questions based on user input"""
        
        # Create question generation agent
        question_agent = OpenRouterAgent(silent=True)
        
        # Get question generation prompt from config
        prompt_template = self.config['orchestrator']['question_generation_prompt']
        generation_prompt = prompt_template.format(
            user_input=user_input,
            num_agents=num_agents
        )
        
        # Remove task completion tool to avoid issues
        question_agent.tools = [tool for tool in question_agent.tools if tool.get('function', {}).get('name') != 'mark_task_complete']
        question_agent.tool_mapping = {name: func for name, func in question_agent.tool_mapping.items() if name != 'mark_task_complete'}
        
        try:
            # Get AI-generated questions
            response = question_agent.run(generation_prompt)
            
            # Parse JSON response
            questions = json.loads(response.strip())
            
            # Validate we got the right number of questions
            if len(questions) != num_agents:
                raise ValueError(f"Expected {num_agents} questions, got {len(questions)}")
            
            return questions
            
        except (json.JSONDecodeError, ValueError) as e:
            # Fallback: create simple variations if AI fails
            return [
                f"Research comprehensive information about: {user_input}",
                f"Analyze and provide insights about: {user_input}",
                f"Find alternative perspectives on: {user_input}",
                f"Verify and cross-check facts about: {user_input}"
            ][:num_agents]
    
    def update_agent_progress(self, agent_id: int, status: str, result: str = None):
        """Thread-safe progress tracking"""
        with self.progress_lock:
            self.agent_progress[agent_id] = status
            if result is not None:
                self.agent_results[agent_id] = result
    
    def run_agent_parallel(self, agent_id: int, subtask: str) -> Dict[str, Any]:
        """
        Run a single agent with the given subtask (synchronous fallback).
        Returns result dictionary with agent_id, status, and response.
        """
        try:
            self.update_agent_progress(agent_id, "PROCESSING...")

            # Use simple agent like in main.py
            agent = OpenRouterAgent(silent=True)

            start_time = time.time()
            response = agent.run(subtask)
            execution_time = time.time() - start_time

            self.update_agent_progress(agent_id, "COMPLETED", response)

            return {
                "agent_id": agent_id,
                "status": "success",
                "response": response,
                "execution_time": execution_time
            }

        except Exception as e:
            # Simple error handling
            return {
                "agent_id": agent_id,
                "status": "error",
                "response": f"Error: {str(e)}",
                "execution_time": 0
            }

    async def run_agent_async(self, agent_id: int, subtask: str) -> Dict[str, Any]:
        """Asynchronous agent execution used with Tygent."""
        try:
            self.update_agent_progress(agent_id, "PROCESSING...")
            agent = OpenRouterAgent(silent=True)
            start_time = time.time()
            response = await agent.run_async(subtask)
            execution_time = time.time() - start_time
            self.update_agent_progress(agent_id, "COMPLETED", response)
            return {
                "agent_id": agent_id,
                "status": "success",
                "response": response,
                "execution_time": execution_time,
            }
        except Exception as e:
            return {
                "agent_id": agent_id,
                "status": "error",
                "response": f"Error: {str(e)}",
                "execution_time": 0,
            }
    
    def aggregate_results(self, agent_results: List[Dict[str, Any]]) -> str:
        """
        Combine results from all agents into a comprehensive final answer.
        Uses the configured aggregation strategy.
        """
        successful_results = [r for r in agent_results if r["status"] == "success"]
        
        if not successful_results:
            return "All agents failed to provide results. Please try again."
        
        # Extract responses for aggregation
        responses = [r["response"] for r in successful_results]
        
        if self.aggregation_strategy == "consensus":
            return self._aggregate_consensus(responses, successful_results)
        else:
            # Default to consensus
            return self._aggregate_consensus(responses, successful_results)
    
    def _aggregate_consensus(self, responses: List[str], _results: List[Dict[str, Any]]) -> str:
        """
        Use one final AI call to synthesize all agent responses into a coherent answer.
        """
        if len(responses) == 1:
            return responses[0]
        
        # Create synthesis agent to combine all responses
        synthesis_agent = OpenRouterAgent(silent=True)
        
        # Build agent responses section
        agent_responses_text = ""
        for i, response in enumerate(responses, 1):
            agent_responses_text += f"=== AGENT {i} RESPONSE ===\n{response}\n\n"
        
        # Get synthesis prompt from config and format it
        synthesis_prompt_template = self.config['orchestrator']['synthesis_prompt']
        synthesis_prompt = synthesis_prompt_template.format(
            num_responses=len(responses),
            agent_responses=agent_responses_text
        )
        
        # Completely remove all tools from synthesis agent to force direct response
        synthesis_agent.tools = []
        synthesis_agent.tool_mapping = {}
        
        # Get the synthesized response
        try:
            final_answer = synthesis_agent.run(synthesis_prompt)
            return final_answer
        except Exception as e:
            # Log the error for debugging
            print(f"\n🚨 SYNTHESIS FAILED: {str(e)}")
            print("📋 Falling back to concatenated responses\n")
            # Fallback: if synthesis fails, concatenate responses
            combined = []
            for i, response in enumerate(responses, 1):
                combined.append(f"=== Agent {i} Response ===")
                combined.append(response)
                combined.append("")
            return "\n".join(combined)
    
    def get_progress_status(self) -> Dict[int, str]:
        """Get current progress status for all agents"""
        with self.progress_lock:
            return self.agent_progress.copy()

    async def _run_agents_with_tygent(self, subtasks: List[str]) -> List[Dict[str, Any]]:
        """Run agents concurrently using Tygent's MultiAgentManager."""

        class WrapperAgent:
            def __init__(self, orchestrator: "TaskOrchestrator", agent_id: int, task: str) -> None:
                self.orchestrator = orchestrator
                self.agent_id = agent_id
                self.task = task

            async def execute(self, _inputs: Dict[str, Any]) -> Dict[str, Any]:
                return await self.orchestrator.run_agent_async(self.agent_id, self.task)

        manager = MultiAgentManager("orchestrator")
        for idx, task in enumerate(subtasks):
            manager.add_agent(f"agent_{idx+1}", WrapperAgent(self, idx, task))

        results_dict = await manager.execute({})

        # Convert results to list sorted by agent id
        results = []
        for idx in range(self.num_agents):
            res = results_dict.get(f"agent_{idx+1}")
            if res is None:
                res = {
                    "agent_id": idx,
                    "status": "error",
                    "response": "No response",
                    "execution_time": 0,
                }
            results.append(res)
        return results
    
    def orchestrate(self, user_input: str):
        """
        Main orchestration method.
        Takes user input, delegates to parallel agents, and returns aggregated result.
        """
        
        # Reset progress tracking
        self.agent_progress = {}
        self.agent_results = {}
        
        # Decompose task into subtasks
        subtasks = self.decompose_task(user_input, self.num_agents)
        
        # Initialize progress tracking
        for i in range(self.num_agents):
            self.agent_progress[i] = "QUEUED"
        
        agent_results = []

        # Execute agents concurrently using Tygent when enabled
        if self.use_tygent:
            try:
                agent_results = asyncio.run(self._run_agents_with_tygent(subtasks))
            except Exception:
                # Fall back to threads if Tygent execution fails
                agent_results = []

        # Use thread pool when Tygent is disabled or failed
        if not agent_results:
            with ThreadPoolExecutor(max_workers=self.num_agents) as executor:
                future_to_agent = {
                    executor.submit(self.run_agent_parallel, i, subtasks[i]): i
                    for i in range(self.num_agents)
                }

                for future in as_completed(future_to_agent, timeout=self.task_timeout):
                    try:
                        result = future.result()
                        agent_results.append(result)
                    except Exception as e:
                        agent_id = future_to_agent[future]
                        agent_results.append({
                            "agent_id": agent_id,
                            "status": "timeout",
                            "response": f"Agent {agent_id + 1} timed out or failed: {str(e)}",
                            "execution_time": self.task_timeout,
                        })
        
        # Sort results by agent_id for consistent output
        agent_results.sort(key=lambda x: x["agent_id"])
        
        # Aggregate results
        final_result = self.aggregate_results(agent_results)
        
        return final_result

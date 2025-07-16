import json
import subprocess
import yaml
import os
import sys
from typing import Dict, Any, List, Optional
from tools import discover_tools


class ClaudeCodeCLIAgent:
    def __init__(self, config_path="config.yaml", silent=False):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Silent mode for orchestrator (suppresses debug output)
        self.silent = silent
        
        # Discover tools dynamically (for compatibility check)
        self.discovered_tools = discover_tools(self.config, silent=self.silent)
        
        # Build tool mapping (kept for interface compatibility)
        self.tool_mapping = {name: tool.execute for name, tool in self.discovered_tools.items()}
        
        # Add tools attribute for orchestrator compatibility
        self.tools = []  # Claude Code doesn't use OpenAI-style tools
        
        # Get Claude Code specific config
        self.claude_config = self.config.get('claude_code', {})
        
        # Get max iterations from config
        self.max_iterations = self.config.get('agent', {}).get('max_iterations', 10)
        
        # Get base system prompt
        self.base_system_prompt = self.config.get('system_prompt', '')
        
        # Build enhanced system prompt with tool instructions
        self.system_prompt = self._build_enhanced_system_prompt()
        
        # Get CLI path (default to 'claude' if not specified)
        self.cli_path = self.claude_config.get('cli_path', 'claude')
        
        # Verify Claude CLI is installed
        self._verify_cli_installed()
        
        # Debug: Print system prompt preview only in debug mode
        if os.environ.get('DEBUG_CLAUDE_CLI'):
            lines = self.system_prompt.split('\n')[:10]
            print("📋 System prompt preview:")
            for line in lines[:5]:
                print(f"   {line[:80]}..." if len(line) > 80 else f"   {line}")
            print(f"   ... ({len(self.system_prompt)} total characters)")
    
    def _verify_cli_installed(self):
        """Verify Claude CLI is installed and accessible"""
        try:
            # Run claude --help to check if CLI is installed
            result = subprocess.run(
                [self.cli_path, '--help'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Claude CLI returned error: {result.stderr}")
            
            if not self.silent:
                print("✓ Claude CLI verified")
                
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude CLI not found at '{self.cli_path}'. "
                "Please install with: npm install -g @anthropic-ai/claude-code"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude CLI verification timed out")
        except Exception as e:
            raise RuntimeError(f"Failed to verify Claude CLI: {e}")
    
    def _build_enhanced_system_prompt(self) -> str:
        """Build system prompt with instructions for using our custom tools"""
        prompt_parts = [self.base_system_prompt]
        
        # Add clear instructions about tool usage
        prompt_parts.append("\n\n## IMPORTANT: Tool Usage Instructions")
        prompt_parts.append("You have access to custom tools through a Python bridge script.")
        prompt_parts.append("To use ANY of the custom tools listed below, you MUST:")
        prompt_parts.append("1. Use the Bash tool")
        prompt_parts.append("2. Run the command: python use_tool.py <tool_name> '<args>...</args>'")
        prompt_parts.append("")
        prompt_parts.append("CRITICAL: Use XML format wrapped in single quotes to avoid JSON escaping issues.")
        prompt_parts.append("The XML format is simple: <args><param>value</param></args>")
        prompt_parts.append("DO NOT try to use tools directly - they are only accessible through the use_tool.py bridge.")
        prompt_parts.append("")
        
        # Add instructions for using the tool bridge
        prompt_parts.append("## Available Custom Tools")
        
        # List available tools with specific examples
        for tool_name, tool in self.discovered_tools.items():
            prompt_parts.append(f"\n### {tool_name}")
            prompt_parts.append(f"Description: {tool.description}")
            
            # Provide concrete examples for each tool
            if tool_name == "search_web":
                prompt_parts.append("Example usage:")
                prompt_parts.append("```bash")
                prompt_parts.append("python use_tool.py search_web '<args><query>latest AI news</query><max_results>5</max_results></args>'")
                prompt_parts.append("```")
            elif tool_name == "calculate":
                prompt_parts.append("Example usage:")
                prompt_parts.append("```bash")
                prompt_parts.append("python use_tool.py calculate '<args><expression>2 + 2 * 3</expression></args>'")
                prompt_parts.append("```")
            elif tool_name == "read_file":
                prompt_parts.append("Example usage:")
                prompt_parts.append("```bash")
                prompt_parts.append("python use_tool.py read_file '<args><path>example.txt</path></args>'")
                prompt_parts.append("```")
            elif tool_name == "write_file":
                prompt_parts.append("Example usage:")
                prompt_parts.append("```bash")
                prompt_parts.append("python use_tool.py write_file '<args><path>output.txt</path><content>Hello World</content></args>'")
                prompt_parts.append("```")
            elif tool_name == "mark_task_complete":
                prompt_parts.append("Example usage:")
                prompt_parts.append("```bash")
                prompt_parts.append("python use_tool.py mark_task_complete '<args><task_summary>Calculated 2+2</task_summary><completion_message>The answer is 4</completion_message></args>'")
                prompt_parts.append("```")
        
        # Final reminder
        prompt_parts.append("\n## Task Completion")
        prompt_parts.append("IMPORTANT: When you have fully completed the user's request, you MUST use the Bash tool to run:")
        prompt_parts.append("python use_tool.py mark_task_complete '<args><task_summary>brief summary</task_summary><completion_message>final message</completion_message></args>'")
        prompt_parts.append("This signals that the task is finished and stops the iteration loop.")
        
        return "\n".join(prompt_parts)
    
    def _parse_streaming_json(self, process: subprocess.Popen) -> str:
        """Parse streaming JSON output from Claude Code CLI"""
        full_response_content = []
        task_completed = False
        iteration_count = 0
        total_cost = 0.0
        
        try:
            for line in process.stdout:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                
                try:
                    message = json.loads(line)
                    
                    # Handle different message types
                    if message.get('type') == 'system' and message.get('subtype') == 'init':
                        if not self.silent:
                            print(f"🤖 Using Claude Code CLI with model: {message.get('model', 'default')}")
                            print(f"📂 Working directory: {message.get('cwd', 'unknown')}")
                    
                    elif message.get('type') == 'assistant':
                        # Extract text content from assistant messages
                        assistant_msg = message.get('message', {})
                        
                        # Count iterations
                        iteration_count += 1
                        if not self.silent:
                            print(f"🔄 Claude Code turn {iteration_count}/{self.max_iterations}")
                        
                        # Process content blocks
                        for content_block in assistant_msg.get('content', []):
                            if content_block.get('type') == 'text':
                                text = content_block.get('text', '')
                                if text:
                                    full_response_content.append(text)
                            
                            elif content_block.get('type') == 'tool_use':
                                tool_name = content_block.get('name', '')
                                if not self.silent:
                                    print(f"   📞 Claude Code using tool: {tool_name}")
                                
                                # Check for tool bridge usage
                                if tool_name == 'Bash':
                                    tool_input = content_block.get('input', {})
                                    command = tool_input.get('command', '')
                                    if 'use_tool.py' in command and 'mark_task_complete' in command:
                                        task_completed = True
                                        if not self.silent:
                                            print("✅ Task completion tool called")
                    
                    elif message.get('type') == 'user':
                        # Tool results come back as user messages
                        pass
                    
                    elif message.get('type') == 'result':
                        # Final result message
                        if message.get('subtype') == 'success':
                            result_text = message.get('result', '')
                            if result_text and result_text not in full_response_content:
                                full_response_content.append(result_text)
                        
                        # Track cost
                        if 'total_cost_usd' in message:
                            total_cost = message['total_cost_usd']
                            if not self.silent and total_cost > 0:
                                print(f"💰 Cost: ${total_cost:.4f}")
                        
                        # Handle errors
                        if message.get('is_error'):
                            error_subtype = message.get('subtype', 'unknown_error')
                            if error_subtype == 'error_max_turns':
                                if not self.silent:
                                    print("⚠️ Maximum turns reached")
                            else:
                                if not self.silent:
                                    print(f"❌ Error: {error_subtype}")
                
                except json.JSONDecodeError as e:
                    if not self.silent:
                        print(f"⚠️ Failed to parse JSON: {line[:50]}...")
                    continue
        
        except Exception as e:
            if not self.silent:
                print(f"❌ Error reading output: {e}")
        
        # Read any errors
        stderr_output = process.stderr.read().decode('utf-8').strip()
        if stderr_output and not self.silent:
            print(f"❌ CLI Error: {stderr_output}")
        
        return "\n\n".join(full_response_content)
    
    def run(self, user_input: str) -> str:
        """Run the agent with user input and return FULL conversation content"""
        if not self.silent:
            print(f"🤖 Using Claude Code CLI provider")
        
        # Build command
        cmd = [
            self.cli_path,
            '-p', user_input,  # Print mode with prompt
            '--output-format', 'stream-json',  # Streaming JSON for parsing
            '--verbose',  # Required for stream-json output
            '--system-prompt', self.system_prompt,
            '--max-turns', str(self.max_iterations),
            '--allowedTools', 'Bash(python use_tool.py *)'
        ]
        
        # Add model if specified
        if 'model' in self.claude_config:
            cmd.extend(['--model', self.claude_config['model']])
        
        # Set working directory to project root
        cwd = os.path.dirname(os.path.abspath(__file__))
        
        try:
            # Run subprocess
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                text=False  # We'll decode manually for better control
            )
            
            # Parse streaming output
            result = self._parse_streaming_json(process)
            
            # Wait for process to complete
            process.wait()
            
            if process.returncode != 0 and not self.silent:
                print(f"⚠️ Claude Code CLI exited with code: {process.returncode}")
            
            return result
            
        except FileNotFoundError:
            error_msg = (
                f"Claude Code CLI not found at '{self.cli_path}'. "
                f"Please install with: npm install -g @anthropic-ai/claude-code"
            )
            if not self.silent:
                print(f"❌ {error_msg}")
            return error_msg
        except Exception as e:
            error_msg = f"Claude Code CLI execution failed: {str(e)}"
            if not self.silent:
                print(f"❌ {error_msg}")
            return error_msg
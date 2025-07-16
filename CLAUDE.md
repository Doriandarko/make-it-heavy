# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

"Make It Heavy" is a Python framework that emulates Grok Heavy functionality using a multi-agent system built on OpenRouter's API. It features intelligent agent orchestration for comprehensive, multi-perspective analysis.

## Development Commands

### Running the Application

```bash
# Single agent mode - runs one agent with all tools
uv run main.py

# Multi-agent orchestration mode (Grok Heavy emulation) - runs 4 parallel agents
uv run make_it_heavy.py
```

### Installing Dependencies

```bash
# Using uv (recommended)
uv pip install -r requirements.txt

# Using standard pip
pip install -r requirements.txt
```

## Architecture Overview

### Core Components

1. **Agent System (`agent.py`)**
   - Implements the agentic loop that continues until task completion
   - Manages tool discovery and execution through `tools/` directory
   - Handles OpenRouter API communication with function calling

2. **Orchestrator (`orchestrator.py`)**
   - Dynamically generates specialized questions using AI
   - Manages parallel execution of multiple agents
   - Synthesizes responses from all agents into comprehensive output

3. **Tool System (`tools/`)**
   - Auto-discovery mechanism in `__init__.py` loads all tools automatically
   - Base class `BaseTool` defines the interface for all tools
   - New tools can be added by creating files that inherit from `BaseTool`

### Key Design Patterns

- **Dynamic Tool Loading**: Tools are discovered at runtime from the `tools/` directory
- **Agentic Loop**: Agents iterate until they call `mark_task_complete`
- **Parallel Execution**: Orchestrator uses ThreadPoolExecutor for concurrent agent runs
- **AI-Driven Decomposition**: Question generation and response synthesis use the configured LLM

## Configuration

All configuration is in `config.yaml`:
- Provider selection (`openrouter` or `claude_code`)
- OpenRouter API settings (key, model selection)
- Claude Code settings (model, max turns, permission mode)
- Agent behavior (max iterations, system prompts)
- Orchestrator settings (parallel agents count, timeouts)
- Tool-specific settings

### Using Claude Code Provider

To use Claude Code instead of OpenRouter:
1. Install Claude Code CLI: `npm install -g @anthropic-ai/claude-code`
2. Change provider in config.yaml: `provider: "claude_code"`
3. Configure Claude Code settings in the `claude_code` section
4. The default model is Claude 4 (claude-sonnet-4-20250514)

#### How Claude Code Integration Works

The Claude Code provider uses a tool bridge approach:
- `use_tool.py` acts as a bridge between Claude Code and our custom tools
- Claude Code runs `python use_tool.py <tool_name> '<args>...</args>'` via its Bash tool
- Uses XML format to avoid JSON escaping issues (e.g., `<args><expression>2+2</expression></args>`)
- This allows Claude Code to use all our custom tools (search_web, calculate, etc.)
- The agent continues iterating until `mark_task_complete` is called

#### Technical Implementation
- Uses subprocess to call Claude Code CLI directly
- Parses streaming JSON output for real-time progress
- Handles tool permissions with `--allowedTools "Bash(python use_tool.py *)"`
- Detects task completion from tool calls

## Important Considerations

- **Context Window**: When selecting models in config.yaml, ensure high context window (200k+ tokens) for orchestrator synthesis
- **API Key**: Must be set in config.yaml before running
- **Tool Development**: New tools must implement `name`, `description`, `parameters`, and `execute` methods from `BaseTool`
import os
import importlib
from typing import Dict, List
from .base_tool import BaseTool

def discover_tools(config: dict = None, silent: bool = False) -> Dict[str, BaseTool]:
    """Automatically discover and load all tools from the tools directory"""
    tools = {}
    
    # Get the tools directory path
    tools_dir = os.path.dirname(__file__)
    
    # Scan for Python files (excluding __init__.py and base_tool.py)
    for filename in os.listdir(tools_dir):
        if filename.endswith('.py') and filename not in ['__init__.py', 'base_tool.py']:
            module_name = filename[:-3]  # Remove .py extension
            
            try:
                # Import the module
                module = importlib.import_module(f'.{module_name}', package='tools')
                
                # Find tool classes that inherit from BaseTool
                for item_name in dir(module):
                    item = getattr(module, item_name)
                    if (isinstance(item, type) and 
                        issubclass(item, BaseTool) and 
                        item != BaseTool):
                        
                        # Instantiate the tool
                        tool_instance = item(config or {})
                        if not tool_instance.enabled:
                            continue
                        tools[tool_instance.name] = tool_instance
                        if not silent:
                            print(f"Loaded tool: {tool_instance.name}")
                        
            except Exception as e:
                if not silent:
                    print(f"Warning: Could not load tool from {filename}: {e}")
    
    return tools

#!/usr/bin/env python3
"""
Tool bridge for Claude Code - allows Claude Code to use Make It Heavy's custom tools
Usage: python use_tool.py <tool_name> '<args>...</args>'

Examples:
    python use_tool.py search_web '<args><query>AI news</query><max_results>5</max_results></args>'
    python use_tool.py calculate '<args><expression>2 + 2 * 3</expression></args>'
    python use_tool.py mark_task_complete '<args><task_summary>Task done</task_summary><completion_message>All completed</completion_message></args>'
"""

import sys
import json
import yaml
import defusedxml.ElementTree as ET
from tools import discover_tools


def parse_xml_args(xml_string):
    """Parse XML arguments into a dictionary"""
    try:
        # Parse the XML
        root = ET.fromstring(xml_string)
        
        # Convert to dictionary
        args = {}
        for child in root:
            # Handle nested elements if needed
            if len(child) > 0:
                # Has children, treat as nested dict
                nested = {}
                for subchild in child:
                    nested[subchild.tag] = subchild.text
                args[child.tag] = nested
            else:
                # Simple element
                args[child.tag] = child.text
                
                # Try to convert to appropriate types
                if child.text:
                    # Try integer
                    try:
                        args[child.tag] = int(child.text)
                    except ValueError:
                        # Try float
                        try:
                            args[child.tag] = float(child.text)
                        except ValueError:
                            # Keep as string
                            pass
        
        return args
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML: {e}")


def main():
    if len(sys.argv) < 3:
        print("Error: Tool name and XML arguments required")
        print("Usage: python use_tool.py <tool_name> '<args>...</args>'")
        print("Example: python use_tool.py calculate '<args><expression>2 + 2</expression></args>'")
        sys.exit(1)
    
    tool_name = sys.argv[1]
    
    # Join all arguments after tool name (in case XML has spaces)
    xml_args = ' '.join(sys.argv[2:])
    
    # Parse XML arguments
    try:
        args = parse_xml_args(xml_args)
    except ValueError as e:
        print(f"Error: {e}")
        print(f"Received: {xml_args[:200]}...")
        print("\nExpected XML format: <args><param>value</param></args>")
        sys.exit(1)
    
    # Load config and discover tools
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config.yaml: {e}")
        sys.exit(1)
    
    # Discover available tools
    tools = discover_tools(config, silent=True)
    
    # Check if tool exists
    if tool_name not in tools:
        print(f"Error: Unknown tool '{tool_name}'")
        print(f"Available tools: {', '.join(tools.keys())}")
        sys.exit(1)
    
    # Execute the tool
    try:
        tool = tools[tool_name]
        result = tool.execute(**args)
        
        # Pretty print the result
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    except TypeError as e:
        print(f"Error: Invalid arguments for tool '{tool_name}': {e}")
        print(f"Expected parameters: {json.dumps(tool.parameters, indent=2)}")
        sys.exit(1)
    except Exception as e:
        print(f"Error executing tool '{tool_name}': {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
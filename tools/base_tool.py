from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseTool(ABC):
    """Base class for all tools"""

    @property
    def enabled(self) -> bool:
        return True
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for OpenRouter function calling"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for OpenRouter"""
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """OpenRouter function parameters schema"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """Execute the tool with given parameters"""
        pass
    
    def to_openrouter_schema(self) -> Dict[str, Any]:
        """Convert tool to OpenRouter function schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

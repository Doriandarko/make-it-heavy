from .base_tool import BaseTool
from ddgs import DDGS
from bs4 import BeautifulSoup
import requests
import json
from parallel_search import ParallelSearchClient, result_rows

class SearchTool(BaseTool):
    def __init__(self, config: dict):
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.get('search', {}).get('enabled', True)
    
    @property
    def name(self) -> str:
        return "search_web"
    
    @property
    def description(self) -> str:
        if self.config.get('search', {}).get('provider') == 'parallel':
            return "Search the web using Parallel for current information and source excerpts. Use fetch_web only when more page context is needed."
        return "Search the web using DuckDuckGo for current information"
    
    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find information on the web"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to return",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    
    def execute(self, query: str, max_results: int = 5) -> list:
        """Search the web using DuckDuckGo and fetch page content"""
        try:
            settings = self.config.get('search', {})
            provider = settings.get('provider', 'duckduckgo')
            if not self.enabled:
                raise ValueError("Web search is disabled")
            if provider not in ('duckduckgo', 'parallel'):
                raise ValueError("Unknown search.provider: " + str(provider))
            if provider == 'parallel':
                if not isinstance(query, str) or not query.strip():
                    raise ValueError("query must be a nonempty string")
                if type(max_results) is not int or not 1 <= max_results <= 20:
                    raise ValueError("max_results must be between 1 and 20")
                result = ParallelSearchClient(settings.get('timeout', 30)).call(
                    'web_search', {'objective': query, 'search_queries': [query]})
                return result_rows(result, max_results)
            # Use ddgs library
            ddgs = DDGS()
            results = ddgs.text(query, max_results=max_results)
            
            simplified_results = []
            
            for result in results:
                try:
                    # Fetch content with requests
                    response = requests.get(
                        result['href'], 
                        headers={'User-Agent': self.config.get('search', {}).get('user_agent', 'Mozilla/5.0')},
                        timeout=10
                    )
                    response.raise_for_status()
                    
                    # Parse HTML with BeautifulSoup
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    
                    # Get text content
                    text = soup.get_text()
                    # Clean up whitespace
                    text = ' '.join(text.split())
                    
                    # Limit content length
                    content_snippet = text[:1000] + "..." if len(text) > 1000 else text
                    
                    simplified_results.append({
                        "title": result['title'],
                        "url": result['href'],
                        "snippet": result['body'],
                        "content": content_snippet
                    })
                
                except Exception as e:
                    # If we can't fetch the page, still include the search result
                    simplified_results.append({
                        "title": result['title'],
                        "url": result['href'],
                        "snippet": result['body'],
                        "content": f"Could not fetch content: {str(e)}"
                    })
            
            return simplified_results
        
        except Exception as e:
            return [{"error": f"Search failed: {str(e)}"}]

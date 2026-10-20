from urllib.parse import urlsplit

from .base_tool import BaseTool
from parallel_search import ParallelSearchClient, result_rows


class FetchTool(BaseTool):
    def __init__(self, config: dict):
        self.settings = config.get('search', {})

    @property
    def enabled(self) -> bool:
        return (self.settings.get('enabled', True)
                and self.settings.get('provider') == 'parallel')

    @property
    def name(self) -> str:
        return 'fetch_web'

    @property
    def description(self) -> str:
        return ('Fetch relevant excerpts from specific web pages using Parallel. '
                'Use only when search excerpts are insufficient or a user asks about a URL.')

    @property
    def parameters(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'urls': {'type': 'array', 'items': {'type': 'string'},
                         'minItems': 1, 'maxItems': 20},
                'objective': {'type': 'string', 'maxLength': 200,
                              'description': 'What information to extract from these pages'},
            },
            'required': ['urls'],
        }

    def execute(self, urls: list, objective: str = '') -> list:
        try:
            if not self.enabled:
                raise ValueError('Parallel page fetching is disabled')
            if not isinstance(urls, list) or not 1 <= len(urls) <= 20:
                raise ValueError('Supply between 1 and 20 HTTP(S) URLs')
            for url in urls:
                parsed = urlsplit(url)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError('Supply HTTP(S) URLs without credentials')
            if not isinstance(objective, str) or len(objective) > 200:
                raise ValueError('objective must be at most 200 characters')
            result = ParallelSearchClient(self.settings.get('timeout', 30)).call(
                'web_fetch', {'urls': urls, 'objective': objective})
            return result_rows(result, len(urls))
        except Exception as error:
            return [{'error': 'Fetch failed: ' + str(error)}]

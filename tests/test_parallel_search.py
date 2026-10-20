"""Scripted model responses exercise the real loader, agent loop and HTTP caller."""
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import yaml

from agent import OpenRouterAgent
from orchestrator import TaskOrchestrator
from parallel_search import ENDPOINT, USER_AGENT, _conversation
from tools import discover_tools


def response(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=content, tool_calls=calls))])


def tool(name, **arguments):
    return SimpleNamespace(id=name, function=SimpleNamespace(
        name=name, arguments=json.dumps(arguments)))


class MCPFixture:
    def __init__(self, sse=False):
        self.requests = []
        self.sse = sse
        self.failure = None
        self.text_result = False
        self.lock = threading.Lock()

    def send(self, session, request, **kwargs):
        payload = json.loads(request.body)
        with self.lock:
            self.requests.append((request, payload, kwargs))
        method = payload['method']
        if method == 'initialize':
            result = {'protocolVersion': '2025-03-26'}
        elif method == 'notifications/initialized':
            reply = requests.Response()
            reply.status_code = 202
            reply._content = b''
            reply._content_consumed = True
            return reply
        elif method == 'tools/list':
            self.assert_session(request)
            result = {'tools': [{'name': 'web_search'}, {'name': 'web_fetch'}]}
        else:
            self.assert_session(request)
            if isinstance(self.failure, BaseException):
                raise self.failure
            args = payload['params']['arguments']
            url = args.get('urls', ['https://example.org/source'])[0]
            result = {'structuredContent': {'results': [
                {'url': url, 'title': 'Source', 'excerpts': ['Verified source excerpt']}],
                'session_id': args['session_id']}, 'content': []}
            if self.failure == 'quota':
                result = {'isError': True, 'content': [{'type': 'text',
                          'text': 'Free-tier rate limit reached'}]}
            elif self.failure == 'rpc':
                result = None
            elif self.text_result:
                result = {'content': [{'type': 'text', 'text': json.dumps(result['structuredContent'])}]}
        message = {'jsonrpc': '2.0', 'id': payload['id'], 'result': result}
        if self.failure == 'rpc' and method == 'tools/call':
            message = {'jsonrpc': '2.0', 'id': payload['id'],
                       'error': {'code': -32602, 'message': 'Bad arguments'}}
        reply = requests.Response()
        reply.status_code = 429 if self.failure == 'http' and method == 'tools/call' else 200
        reply.request = request
        reply.headers['Mcp-Session-Id'] = 'transport-only'
        if self.failure == 'malformed' and method == 'tools/call':
            reply._content = b'not json'
        elif self.sse:
            reply.headers['Content-Type'] = 'text/event-stream'
            reply._content = ('event: message\r\ndata: ' + json.dumps(message) + '\r\n\r\n').encode()
        else:
            reply.headers['Content-Type'] = 'application/json'
            reply._content = json.dumps(message).encode()
        reply._content_consumed = True
        return reply

    @staticmethod
    def assert_session(request):
        assert request.headers['Mcp-Session-Id'] == 'transport-only'
        assert request.headers['MCP-Protocol-Version'] == '2025-03-26'

    def calls(self):
        return [p['params'] for _, p, _ in self.requests if p['method'] == 'tools/call']


class ParallelAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = yaml.safe_load(Path('config.yaml').read_text())
        self.config['openrouter']['api_key'] = 'scripted-test-key'
        self.config['search']['provider'] = 'parallel'
        self.config['search']['timeout'] = 7
        self.path = Path(self.temp.name) / 'config.yaml'
        (Path(self.temp.name) / '.netrc').write_text(
            'machine search.parallel.ai login ignored password must-not-be-sent\n')
        self.save_config()
        self.env = patch.dict(os.environ, {'HOME': self.temp.name,
                              'PARALLEL_API_KEY': 'must-not-be-used'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fixture = MCPFixture()
        fixture = self.fixture
        self.http = patch.object(requests.Session, 'send', autospec=True,
                                 side_effect=fixture.send)
        self.http.start()
        self.addCleanup(self.http.stop)

    def save_config(self):
        self.path.write_text(yaml.safe_dump(self.config))

    def agent(self):
        return OpenRouterAgent(str(self.path), silent=True)

    def run_script(self, agent, calls):
        script = [response(calls=[call]) for call in calls]
        consumed = []

        def llm(messages):
            if messages[-1]['role'] == 'tool':
                consumed.append(json.loads(messages[-1]['content']))
            return script.pop(0) if script else response('Answer from source', [
                tool('mark_task_complete', task_summary='Done', completion_message='Done')])

        with patch.object(agent, 'call_llm', side_effect=llm):
            answer = agent.run('Research this topic')
        self.assertIn('Answer from source', answer)
        return consumed

    def test_search_fetch_followup_reset_and_outgoing_requests(self):
        agent = self.agent()
        consumed = self.run_script(agent, [tool('search_web', query='current science news'),
            tool('fetch_web', urls=['https://example.org/source'], objective='Explain finding'),
            tool('search_web', query='science followup evidence')])
        self.assertEqual(len(consumed), 3)
        self.assertTrue(all(c[0]['content'] == 'Verified source excerpt' for c in consumed))
        first_ids = {c['arguments']['session_id'] for c in self.fixture.calls()}
        self.assertEqual(len(first_ids), 1)
        self.run_script(agent, [tool('search_web', query='independent research')])
        self.assertNotIn(self.fixture.calls()[-1]['arguments']['session_id'], first_ids)
        self.assertIsNone(_conversation.get())
        for request, payload, kwargs in self.fixture.requests:
            self.assertEqual(request.url, ENDPOINT)
            self.assertEqual(request.headers['User-Agent'], USER_AGENT)
            self.assertNotIn('Authorization', request.headers)
            self.assertNotIn('x-api-key', request.headers)
            self.assertEqual(kwargs['timeout'], 7)
            if payload['method'] == 'tools/call':
                self.assertNotEqual(payload['params']['arguments']['session_id'], 'transport-only')

    def test_default_saved_choice_override_and_disabled_tools(self):
        for settings in ({}, {'provider': 'duckduckgo'}, {'provider': 'duckduckgo', 'user_agent': 'Saved UA'}):
            with self.subTest(settings=settings):
                tools = discover_tools({'search': settings}, silent=True)
                self.assertNotIn('fetch_web', tools)
                self.assertIn('DuckDuckGo', tools['search_web'].description)
                with patch('tools.search_tool.DDGS') as ddgs, patch('tools.search_tool.requests.get') as get:
                    ddgs.return_value.text.return_value = [{'href': 'https://example.org', 'title': 'DDG', 'body': 'Snippet'}]
                    get.return_value.text = '<p>Duck content</p>'
                    rows = tools['search_web'].execute('query')
                    self.assertEqual(rows[0]['content'], 'Duck content')
                    self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], settings.get('user_agent', 'Mozilla/5.0'))
        tools = discover_tools({'search': {'provider': 'parallel'}}, silent=True)
        self.assertIn('fetch_web', tools)
        self.assertIn('Parallel', tools['search_web'].description)
        tools = discover_tools({'search': {'provider': 'parallel', 'enabled': False}}, silent=True)
        self.assertNotIn('search_web', tools)
        self.assertNotIn('fetch_web', tools)
        unknown = discover_tools({'search': {'provider': 'typo'}}, silent=True)
        self.assertIn('Unknown search.provider', unknown['search_web'].execute('query')[0]['error'])
        self.assertFalse(self.fixture.calls())

    def test_removed_permission_and_bad_urls_make_no_request(self):
        agent = self.agent()
        del agent.tool_mapping['search_web']
        consumed = self.run_script(agent, [tool('search_web', query='not allowed'),
            tool('fetch_web', urls=['file:///etc/passwd']),
            tool('fetch_web', urls=['https://user:secret@example.org'])])
        self.assertTrue(all('error' in c if isinstance(c, dict) else 'error' in c[0] for c in consumed))
        self.assertFalse(self.fixture.requests)

    def test_errors_and_timeouts_reach_consumer_without_fallback(self):
        for failure in ('quota', 'http', 'rpc', 'malformed', requests.Timeout('Timed out')):
            with self.subTest(failure=failure), patch('tools.search_tool.DDGS') as ddgs:
                self.fixture.failure = failure
                consumed = self.run_script(self.agent(), [tool('search_web', query='test query')])
                self.assertIn('error', consumed[0][0])
                ddgs.assert_not_called()

    def test_quota_followup_keeps_identity(self):
        agent = self.agent()
        responses = iter([response(calls=[tool('search_web', query='first query')]),
                          response(calls=[tool('search_web', query='followup query')]),
                          response('Finished', [tool('mark_task_complete', task_summary='Done', completion_message='Done')])])
        self.fixture.failure = 'quota'
        with patch.object(agent, 'call_llm', side_effect=lambda messages: next(responses)):
            agent.run('One research task')
        self.assertEqual(len({c['arguments']['session_id'] for c in self.fixture.calls()}), 1)

    def test_sse_and_text_block_results(self):
        self.fixture.sse = True
        self.fixture.text_result = True
        consumed = self.run_script(self.agent(), [tool('search_web', query='SSE query')])
        self.assertEqual(consumed[0][0]['content'], 'Verified source excerpt')

    def test_bad_inputs_and_fetch_errors(self):
        agent = self.agent()
        consumed = self.run_script(agent, [tool('search_web', query=''),
            tool('search_web', query='valid', max_results=0),
            tool('search_web', query='valid', max_results=True),
            tool('fetch_web', urls=[]),
            tool('fetch_web', urls=['https://example.org'], objective='x' * 201)])
        self.assertTrue(all('error' in rows[0] for rows in consumed))
        self.assertFalse(self.fixture.requests)
        self.fixture.failure = requests.Timeout('Fetch timed out')
        consumed = self.run_script(agent, [tool('fetch_web', urls=['https://example.org'])])
        self.assertIn('Fetch timed out', consumed[0][0]['error'])

    def test_cancellation_propagates_and_clears_task_context(self):
        self.fixture.failure = KeyboardInterrupt()
        with patch('tools.search_tool.DDGS') as ddgs:
            with self.assertRaises(KeyboardInterrupt):
                self.run_script(self.agent(), [tool('search_web', query='cancel query')])
            ddgs.assert_not_called()
        self.assertIsNone(_conversation.get())

    def test_concurrent_reused_agent_clients_keep_task_identity(self):
        agents = [self.agent(), self.agent()]
        barrier = threading.Barrier(2)

        def execute(agent):
            barrier.wait(timeout=10)
            return self.run_script(agent, [tool('search_web', query='concurrent topic'),
                tool('fetch_web', urls=['https://example.org/source'])])

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, agents))
        self.assertTrue(all(len(r) == 2 for r in results))
        ids = [c['arguments']['session_id'] for c in self.fixture.calls()]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all(ids.count(i) == 2 for i in set(ids)))

    def test_heavy_mode_runs_real_parallel_agent_loops(self):
        orchestrator = TaskOrchestrator(str(self.path), silent=True)
        orchestrator.num_agents = 2

        def scripted_llm(agent, messages):
            tool_messages = [m for m in messages if m['role'] == 'tool']
            if not tool_messages:
                return response(calls=[tool('search_web', query='heavy research topic')])
            rows = json.loads(tool_messages[-1]['content'])
            self.assertEqual(rows[0]['url'], 'https://example.org/source')
            return response(rows[0]['content'], [tool('mark_task_complete', task_summary='Done', completion_message='Done')])

        real_agent = OpenRouterAgent
        with patch('orchestrator.OpenRouterAgent', side_effect=lambda **kw: real_agent(str(self.path), **kw)), \
             patch.object(OpenRouterAgent, 'call_llm', new=scripted_llm), \
             patch.object(orchestrator, 'decompose_task', return_value=['topic one', 'topic two']), \
             patch.object(orchestrator, 'aggregate_results', side_effect=lambda results: '\n'.join(r['response'] for r in results)):
            answer = orchestrator.orchestrate('Research in parallel')
        self.assertEqual(answer.count('Verified source excerpt'), 2)
        self.assertEqual(len({c['arguments']['session_id'] for c in self.fixture.calls()}), 2)


if __name__ == '__main__':
    unittest.main()

"""Small synchronous client for Parallel's anonymous Streamable HTTP MCP endpoint."""
import json
import uuid
from contextvars import ContextVar
from functools import wraps

import requests


ENDPOINT = "https://search.parallel.ai/mcp"
USER_AGENT = "make-it-heavy (+https://github.com/Doriandarko/make-it-heavy)"
_conversation = ContextVar("parallel_search_conversation", default=None)


def search_conversation(run):
    """Each Agent.run is a new research task, including on a reused agent."""
    @wraps(run)
    def wrapped(*args, **kwargs):
        token = _conversation.set(str(uuid.uuid4()))
        try:
            return run(*args, **kwargs)
        finally:
            _conversation.reset(token)
    return wrapped


class ParallelSearchClient:
    def __init__(self, timeout=30):
        self.timeout = float(timeout)
        if not 0 < self.timeout <= 300:
            raise ValueError("search.timeout must be between 0 and 300 seconds")

    def call(self, name, arguments):
        # Transport sessions are deliberately separate from research identity.
        arguments = dict(arguments, session_id=_conversation.get() or str(uuid.uuid4()))
        with requests.Session() as session:
            # Explicit anonymous auth prevents requests from adding .netrc credentials.
            session.auth = lambda request: request
            session.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            })

            def rpc(method, params, request_id=None):
                payload = {"jsonrpc": "2.0", "method": method, "params": params}
                if request_id is not None:
                    payload["id"] = request_id
                with session.post(ENDPOINT, json=payload, timeout=self.timeout) as response:
                    response.raise_for_status()
                    if response.headers.get("Mcp-Session-Id"):
                        session.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                    if request_id is None:
                        return None
                    if "text/event-stream" in response.headers.get("Content-Type", ""):
                        messages = []
                        for event in response.text.replace("\r\n", "\n").split("\n\n"):
                            data = "\n".join(line[5:].lstrip() for line in event.splitlines()
                                             if line.startswith("data:"))
                            if data:
                                messages.append(json.loads(data))
                        message = next((m for m in messages if m.get("id") == request_id), None)
                    else:
                        message = response.json()
                    if not isinstance(message, dict) or message.get("id") != request_id:
                        raise ValueError("Invalid MCP response identity")
                    if "error" in message:
                        raise ValueError("Parallel MCP: " + str(message["error"]))
                    return message["result"]

            initialized = rpc("initialize", {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "make-it-heavy", "version": "1.0"},
            }, 1)
            session.headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
            rpc("notifications/initialized", {})
            tools = rpc("tools/list", {}, 2)
            if name not in {tool["name"] for tool in tools["tools"]}:
                raise ValueError("Parallel MCP does not advertise " + name)
            result = rpc("tools/call", {"name": name, "arguments": arguments}, 3)
            texts = [block["text"] for block in result.get("content", [])
                     if block.get("type") == "text"]
            if result.get("isError"):
                raise ValueError(" ".join(texts) or "Parallel MCP tool failed")
            if isinstance(result.get("structuredContent"), dict):
                return result["structuredContent"]
            # Older MCP servers encode the structured result in a text block.
            return json.loads("\n".join(texts))


def result_rows(result, limit):
    """Keep the existing search_web result shape for the agent consumer."""
    rows = []
    for item in result["results"][:limit]:
        excerpt = "\n".join(item.get("excerpts", []))
        rows.append({"title": item.get("title"), "url": item["url"],
                     "snippet": excerpt, "content": excerpt})
    for error in result.get("errors", []):
        rows.append({"url": error.get("url"), "error": error.get("error_type", "Fetch failed")})
    return rows

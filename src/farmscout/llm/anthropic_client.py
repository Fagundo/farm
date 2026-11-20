"""Claude Messages API client using only the standard library.

Uses the server-side web search tool when ``web_search=True``. Tool type and model
names are configurable because they are versioned by the API.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence

from farmscout.llm.base import LLMClient, LLMError

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
WEB_SEARCH_TOOL_TYPE = "web_search_20250305"


class AnthropicClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        web_search_max_uses: int = 5,
        timeout: float = 120.0,
        retries: int = 3,
    ) -> None:
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._max_uses = web_search_max_uses
        self._timeout = timeout
        self._retries = retries

    def complete(
        self, system: str, user: str, *, web_search: bool = False, allowed_domains: Sequence[str] = ()
    ) -> str:
        body: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if web_search:
            tool = {"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": self._max_uses}
            if allowed_domains:
                tool["allowed_domains"] = list(allowed_domains)
            body["tools"] = [tool]
        data = self._post(body)
        texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        if not texts:
            raise LLMError(f"No text in response (stop_reason={data.get('stop_reason')})")
        return "\n".join(texts)

    def _post(self, body: dict) -> dict:
        payload = json.dumps(body).encode()
        headers = {
            "x-api-key": self._key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        last: Exception | None = None
        for attempt in range(self._retries):
            req = urllib.request.Request(API_URL, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (429, 500, 502, 503, 529):
                    time.sleep(2 ** attempt * 5)
                    continue
                raise LLMError(f"Anthropic API {e.code}: {e.read()[:300]!r}") from e
            except urllib.error.URLError as e:
                last = e
                time.sleep(2 ** attempt)
        raise LLMError(f"Anthropic API failed after {self._retries} attempts: {last}")

"""LLM abstraction so extraction/search depend on an interface, not a vendor."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, *, web_search: bool = False) -> str:
        """Return the model's final text answer."""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_payload(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply (tolerates code fences/prose)."""
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for chunk in candidates:
        chunk = chunk.strip()
        for opener, closer in (("[", "]"), ("{", "}")):
            start, end = chunk.find(opener), chunk.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(chunk[start : end + 1])
                except json.JSONDecodeError:
                    continue
    raise LLMError(f"No JSON found in model reply: {text[:200]!r}")

"""Extremely small subset of jsonpath-ng used in tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple


@dataclass
class Match:
    value: Any


class JSONPath:
    def __init__(self, tokens: List[Tuple[str, Any]]):
        self.tokens = tokens

    def find(self, data: Any) -> List[Match]:
        results = [Match(value) for value in self._walk(data, 0)]
        return results

    def _walk(self, current: Any, index: int):
        if index >= len(self.tokens):
            yield current
            return
        token_type, token_value = self.tokens[index]
        if token_type == "field":
            if isinstance(current, dict) and token_value in current:
                yield from self._walk(current[token_value], index + 1)
        elif token_type == "wildcard":
            if isinstance(current, list):
                for item in current:
                    yield from self._walk(item, index + 1)
            elif isinstance(current, dict):
                for item in current.values():
                    yield from self._walk(item, index + 1)
        elif token_type == "filter":
            if isinstance(current, list):
                field, expected = token_value
                for item in current:
                    if isinstance(item, dict) and item.get(field) == expected:
                        yield from self._walk(item, index + 1)
        elif token_type == "index":
            if isinstance(current, list):
                try:
                    yield from self._walk(current[token_value], index + 1)
                except IndexError:
                    return
        else:
            return


def parse(path: str) -> JSONPath:
    if not path.startswith("$"):
        raise ValueError("JSONPath must start with $")
    tokens: List[Tuple[str, Any]] = []
    i = 1
    while i < len(path):
        if path[i] == ".":
            i += 1
            start = i
            while i < len(path) and path[i] not in ".[":
                i += 1
            tokens.append(("field", path[start:i]))
        elif path[i] == "[":
            end = path.find("]", i)
            if end == -1:
                raise ValueError("Unclosed bracket")
            inside = path[i + 1 : end]
            if inside == "*":
                tokens.append(("wildcard", None))
            elif inside.startswith("?"):
                # expect format ?(@.field=='value')
                condition = inside[2:-1]  # remove ?(@ and )
                field, _, value = condition.partition("==")
                field = field.replace("@.", "").strip()
                value = value.strip().strip("'").strip('"')
                tokens.append(("filter", (field, value)))
            else:
                try:
                    index = int(inside)
                except ValueError:
                    tokens.append(("field", inside))
                else:
                    tokens.append(("index", index))
            i = end + 1
        else:
            i += 1
    return JSONPath(tokens)


__all__ = ["parse", "JSONPath", "Match"]

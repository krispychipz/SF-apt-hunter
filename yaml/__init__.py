"""Very small YAML subset loader for config files."""
from __future__ import annotations

import re
from typing import Any, Tuple


def safe_load(text: str) -> Any:
    lines = text.splitlines()
    value, _ = _parse_block(lines, 0, 0)
    return value


def _parse_block(lines: list[str], index: int, indent: int) -> Tuple[Any, int]:
    mapping: dict[str, Any] = {}
    sequence: list[Any] = []
    is_sequence = False
    i = index
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        current_indent = len(raw) - len(raw.lstrip(" "))
        if current_indent < indent:
            break
        stripped = raw.strip()
        if stripped.startswith("- "):
            is_sequence = True
            item = stripped[2:].strip()
            if item:
                sequence.append(_parse_scalar(item))
                i += 1
            else:
                value, new_index = _parse_block(lines, i + 1, current_indent + 2)
                sequence.append(value)
                i = new_index
        else:
            key, _, remainder = stripped.partition(":")
            key = key.strip()
            remainder = remainder.strip()
            if remainder:
                mapping[key] = _parse_scalar(remainder)
                i += 1
            else:
                value, new_index = _parse_block(lines, i + 1, current_indent + 2)
                mapping[key] = value
                i = new_index
    if is_sequence:
        return sequence, i
    return mapping, i


def _parse_scalar(token: str) -> Any:
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        parts = [part.strip() for part in inner.split(",")]
        return [_parse_scalar(part) for part in parts]
    if token.lower() in {"true", "false"}:
        return token.lower() == "true"
    if token.lower() in {"null", "none", "~"}:
        return None
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    if token.startswith('"') and token.endswith('"'):
        # unescape simple sequences
        body = token[1:-1]
        body = body.replace("\\\"", '"').replace("\\n", "\n")
        return body
    # numbers
    if re.fullmatch(r"[-+]?[0-9]+", token):
        return int(token)
    if re.fullmatch(r"[-+]?[0-9]*\.[0-9]+", token):
        return float(token)
    return token


__all__ = ["safe_load"]

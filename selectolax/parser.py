"""Simplified selectolax-like HTML parser for fixtures."""
from __future__ import annotations

from html.parser import HTMLParser as _HTMLParser
from typing import Any, Dict, List, Optional


class Node:
    def __init__(self, tag: str, attrs: Dict[str, str], parent: Optional["Node"] = None):
        self.tag = tag
        self.attributes = attrs
        self.parent = parent
        self.children: List[Node] = []
        self._text_segments: List[str] = []

    def append_child(self, node: "Node") -> None:
        self.children.append(node)

    def append_text(self, text: str) -> None:
        if text:
            self._text_segments.append(text)

    def text(self, strip: bool = False) -> str:
        content = "".join(self._text_segments) + "".join(child.text(False) for child in self.children)
        return content.strip() if strip else content

    def css(self, selector: str) -> List["Node"]:
        parts = [part.strip() for part in selector.split(" ") if part.strip()]
        return self._select(parts)

    def css_first(self, selector: str) -> Optional["Node"]:
        matches = self.css(selector)
        return matches[0] if matches else None

    def _select(self, parts: List[str]) -> List["Node"]:
        if not parts:
            return []
        matches: List[Node] = []
        for node in self._iter_descendants(include_self=True):
            if _match_simple(node, parts[0]):
                if len(parts) == 1:
                    matches.append(node)
                else:
                    matches.extend(node._select(parts[1:]))
        return matches

    def _iter_descendants(self, include_self: bool = False):
        if include_self:
            yield self
        for child in self.children:
            yield child
            yield from child._iter_descendants()


class _SelectolaxParser(_HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]):
        attr_dict = {k: (v or "") for k, v in attrs}
        node = Node(tag, attr_dict, parent=self.stack[-1])
        self.stack[-1].append_child(node)
        self.stack.append(node)

    def handle_endtag(self, tag: str):
        if len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data: str):
        self.stack[-1].append_text(data)


class HTMLParser:
    def __init__(self, html: str):
        parser = _SelectolaxParser()
        parser.feed(html)
        parser.close()
        self._root = parser.root

    def css(self, selector: str) -> List[Node]:
        return self._root.css(selector)

    def css_first(self, selector: str) -> Optional[Node]:
        return self._root.css_first(selector)


def _match_simple(node: Node, selector: str) -> bool:
    if not selector:
        return False
    tag_part = selector
    attr_filters: Dict[str, str] = {}
    if "[" in selector and selector.endswith("]"):
        tag_part, attr_part = selector.split("[", 1)
        attr_part = attr_part.rstrip("]")
        if "=" in attr_part:
            attr_name, attr_value = attr_part.split("=", 1)
            attr_filters[attr_name.strip()] = attr_value.strip().strip("'").strip('"')
        tag_part = tag_part.strip()
    else:
        tag_part = selector
    classes = []
    if "." in tag_part:
        pieces = tag_part.split(".")
        tag_name = pieces[0] or None
        classes = [p for p in pieces[1:] if p]
    else:
        tag_name = tag_part or None
    if tag_name and node.tag != tag_name:
        return False
    if classes:
        class_attr = node.attributes.get("class", "")
        tokens = {c for c in class_attr.split() if c}
        for cls in classes:
            if cls not in tokens:
                return False
    for attr_name, attr_value in attr_filters.items():
        if node.attributes.get(attr_name) != attr_value:
            return False
    if not tag_name and not classes and attr_filters:
        return bool(attr_filters)
    return tag_name is None or node.tag == tag_name or bool(classes)


__all__ = ["HTMLParser", "Node"]

"""Minimal BeautifulSoup fallback used when the real library is unavailable."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Dict, Generator, List, Optional, Tuple, Union


class Node:
    """A very small subset of :class:`bs4.element.Tag`."""

    def __init__(self, name: str, attrs: Optional[Dict[str, Union[str, List[str]]]] = None, parent: Optional["Node"] = None) -> None:
        self.name = name
        self.attrs = attrs or {}
        self.parent = parent
        self.contents: List[Union["Node", str]] = []
        self.sourceline = 0
        self.sourcepos = 0

    def append(self, item: Union["Node", str]) -> None:
        self.contents.append(item)

    def find_all(self, name: Union[str, bool] = True) -> List["Node"]:
        matches: List[Node] = []
        for child in self._descendants():
            if isinstance(child, Node) and _matches_name(child, name):
                matches.append(child)
        return matches

    def get(self, key: str, default=None):  # type: ignore[override]
        return self.attrs.get(key, default)

    def get_text(self, separator: str = "", strip: bool = False) -> str:
        strings = list(self._iter_strings())
        if strip:
            strings = [s.strip() for s in strings if s.strip()]
        result = separator.join(strings)
        return result.strip() if strip else result

    @property
    def stripped_strings(self) -> Generator[str, None, None]:
        for string in self._iter_strings():
            stripped = string.strip()
            if stripped:
                yield stripped

    @property
    def parents(self) -> Generator["Node", None, None]:
        current = self.parent
        while current is not None:
            yield current
            current = current.parent

    def _iter_strings(self) -> Generator[str, None, None]:
        for item in self.contents:
            if isinstance(item, str):
                yield item
            else:
                yield from item._iter_strings()

    def _descendants(self) -> Generator[Union["Node", str], None, None]:
        for item in self.contents:
            yield item
            if isinstance(item, Node):
                yield from item._descendants()


class _SoupBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes: Dict[str, Union[str, List[str]]] = {}
        for key, value in attrs:
            if key == "class" and value is not None:
                attributes[key] = value.split()
            elif value is not None:
                attributes[key] = value
        node = Node(tag, attributes, parent=self.current)
        self.current.append(node)
        self.current = node

    def handle_endtag(self, tag: str) -> None:
        current = self.current
        while current.parent is not None and current.name != tag:
            current = current.parent
        if current.parent is not None:
            self.current = current.parent

    def handle_data(self, data: str) -> None:
        if data:
            self.current.append(data)

    def error(self, message: str) -> None:  # pragma: no cover - required abstract method
        raise RuntimeError(message)


class BeautifulSoup(Node):
    """A minimal drop-in stand-in for :class:`bs4.BeautifulSoup`."""

    def __init__(self, markup: str, parser: str | None = None) -> None:
        builder = _SoupBuilder()
        builder.feed(markup)
        super().__init__("document", {})
        self.contents = builder.root.contents

    def find_all(self, name: Union[str, bool] = True) -> List[Node]:  # type: ignore[override]
        matches: List[Node] = []
        for item in self._descendants():
            if isinstance(item, Node) and _matches_name(item, name):
                matches.append(item)
        return matches


Tag = Node


def _matches_name(node: Node, name: Union[str, bool]) -> bool:
    if name in (True, None):
        return True
    return node.name == name

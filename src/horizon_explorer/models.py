from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Control:
    kind: str
    label: str
    name: str | None
    value_hint: str | None
    risk: str


@dataclass
class Link:
    text: str
    url: str
    risk: str


@dataclass
class PageEvidence:
    url: str
    title: str
    headings: list[str]
    tabs: list[str]
    links: list[Link]
    controls: list[Control]
    forms: list[str]
    visited_at: str = field(default_factory=utc_now)


@dataclass
class Evidence:
    schema_version: str = "1.0"
    generated_at: str = field(default_factory=utc_now)
    pages: list[PageEvidence] = field(default_factory=list)
    visited_pages: list[dict[str, str]] = field(default_factory=list)
    blocked_items: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


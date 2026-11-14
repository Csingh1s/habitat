from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .classify import classify

_FOOTER = re.compile(r"\d+ [A-Za-z ]+ Drive,.*?REFERENCE", re.S)
_SECTIONS = ("ROOFING", "EXTERIOR", "STRUCTURE", "ELECTRICAL", "HEATING", "COOLING",
             "INSULATION", "PLUMBING", "INTERIOR")
_SECTION_AREA = {"ROOFING": "exterior", "EXTERIOR": "exterior", "INTERIOR": "interior"}
_FINDING = re.compile(
    r"Condition:\s*(?P<body>.*?)(?:Implication\(s\):\s*(?P<impl>.*?))?"
    r"Location:\s*(?P<loc>.*?)\s+Task:\s*(?P<task>.*?)(?:\s+Time:|\s+Cost:|$)",
    re.S,
)


@dataclass(frozen=True)
class Finding:
    page: int
    section: str
    title: str
    description: str
    location: str
    task: str
    area: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_findings(pdf_path: Path) -> list[Finding]:
    reader = PdfReader(str(pdf_path))
    findings: list[Finding] = []
    section = ""
    for page_no, page in enumerate(reader.pages, start=1):
        text = _FOOTER.sub("", page.extract_text() or "")
        for line in text.splitlines():
            if line.strip() in _SECTIONS:
                section = line.strip()
        for m in _FINDING.finditer(text):
            body = m.group("body").strip()
            title, _, rest = body.partition("\n")
            location = _clean(m.group("loc"))
            description = _clean(rest) or _clean(title)
            area = classify(f"{location} {title}").area
            if area == "needs_review":
                area = _SECTION_AREA.get(section, "needs_review")
            findings.append(
                Finding(page_no, section, _clean(title), description, location,
                        _clean(m.group("task")), area)
            )
    return findings

"""Rule-based clause segmentation for Turkish (and simple English) contracts.

Heading styles, in order of preference (the first style that applies wins):

1. Article headings: "MADDE 1 - KONU", "Madde 1:", "MADDE 1.", "Madde 1 Taraflar",
   "ARTICLE 1". Numbered lines inside an article stay in the article body.
2. Top-level numbered headings: "1. TARAFLAR", "1) Konu". They must run in
   sequence (1, 2, 3, ...) with the same marker, which rejects numbered lists
   restarting inside a clause, dates ("01.02.2024") and amounts ("450.000 TL").
   Sub-numbers ("1.1", "2.3.") stay inside their parent clause.
3. Sub-numbered headings only ("1.1", "1.2", "2.1"): used when the document has
   no top-level headings at all.
4. Fallback: paragraphs (blocks separated by blank lines, else single lines).

Text before the first heading (title, contract number, parties block) is kept as
a preamble clause with id "preamble", so nothing in the document is discarded; it
often carries signals such as "KONUT KİRA SÖZLEŞMESİ" or the parties' details.
"""

import re
from dataclasses import dataclass

from .models import Clause

_SEPARATORS = "-–—:.)"
_ARTICLE_RE = re.compile(
    r"^(?:MADDE|Madde|madde|ARTICLE|Article)\s*[-:]?\s*(?P<num>[1-9]\d{0,2})"
    r"(?!\s*\.\d)(?!\d)"
    r"(?P<rest>\s*[" + re.escape(_SEPARATORS) + r"].*|\s+\S.*|\s*)$"
)
_TOP_NUMBERED_RE = re.compile(r"^(?P<num>[1-9]\d?)\s*(?P<marker>[.)])\s+(?P<rest>\S.*)$")
_SUB_NUMBERED_RE = re.compile(
    r"^(?P<num>[1-9]\d?)\.(?P<sub>[1-9]\d?)(?:\.\d{1,2})*\.?\s+(?P<rest>\S.*)$"
)
_CURRENCY_RE = re.compile(r"^(?:TL|TRY|USD|EUR|€|\$|₺|%|YTL|bin|milyon)\b", re.IGNORECASE)
# A heading whose text is longer than this is treated as a numbered paragraph:
# the heading line itself is part of the clause text.
_HEADING_TEXT_MAX = 80


@dataclass
class _Heading:
    index: int
    title: str
    rest: str


def segment_clauses(text: str) -> list[Clause]:
    lines = [line.strip() for line in text.splitlines()]
    non_empty = [line for line in lines if line]
    for finder in (_article_headings, _top_numbered_headings, _sub_numbered_headings):
        headings = finder(non_empty)
        if headings:
            return _build_clauses(non_empty, headings)
    return _paragraph_clauses(lines)


def _article_headings(lines: list[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    for index, line in enumerate(lines):
        match = _ARTICLE_RE.match(line)
        if not match:
            continue
        rest = match.group("rest").strip()
        # "Madde 5 uyarınca ..." is a cross reference, not a heading.
        if rest and rest[0] not in _SEPARATORS and not rest[0].isupper():
            continue
        if rest and rest[0] in _SEPARATORS:
            rest = rest[1:].strip()
        headings.append(_Heading(index=index, title=line, rest=rest))
    return headings


def _top_numbered_headings(lines: list[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    marker: str | None = None
    expected = 1
    for index, line in enumerate(lines):
        match = _TOP_NUMBERED_RE.match(line)
        if not match or _CURRENCY_RE.match(match.group("rest")):
            continue
        number = int(match.group("num"))
        if number != expected:
            continue
        if marker is not None and match.group("marker") != marker:
            continue
        marker = match.group("marker")
        expected += 1
        headings.append(_Heading(index=index, title=line, rest=match.group("rest").strip()))
    return headings if len(headings) >= 2 else []


def _sub_numbered_headings(lines: list[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    last: tuple[int, int] = (0, 0)
    for index, line in enumerate(lines):
        match = _SUB_NUMBERED_RE.match(line)
        if not match or _CURRENCY_RE.match(match.group("rest")):
            continue
        current = (int(match.group("num")), int(match.group("sub")))
        # Only accept "1.1", "1.2", "2.1" style progressions; deeper levels stay in the body.
        if line.split()[0].rstrip(".").count(".") != 1:
            continue
        if current <= last:
            continue
        last = current
        headings.append(_Heading(index=index, title=line, rest=match.group("rest").strip()))
    return headings if len(headings) >= 2 else []


PREAMBLE_ID = "preamble"
PREAMBLE_TITLE = "Başlangıç"


def _build_clauses(lines: list[str], headings: list[_Heading]) -> list[Clause]:
    clauses: list[Clause] = []
    preamble = lines[: headings[0].index] if headings else []
    if preamble:
        preamble_clause = Clause(id=PREAMBLE_ID, title=PREAMBLE_TITLE, text=" ".join(preamble))
    bounds = [heading.index for heading in headings] + [len(lines)]
    for position, heading in enumerate(headings):
        body = lines[heading.index + 1 : bounds[position + 1]]
        is_paragraph_heading = len(heading.rest) > _HEADING_TEXT_MAX
        parts = ([heading.rest] if is_paragraph_heading else []) + body
        clause_text = " ".join(parts).strip() or heading.title
        clauses.append(
            Clause(
                id=f"clause-{len(clauses) + 1}",
                title=_short_title(heading.title),
                text=clause_text,
            )
        )
    return ([preamble_clause] if preamble else []) + clauses


def _short_title(title: str) -> str:
    if len(title) <= _HEADING_TEXT_MAX + 10:
        return title
    return title[:_HEADING_TEXT_MAX].rstrip() + "..."


def _paragraph_clauses(lines: list[str]) -> list[Clause]:
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    if len(blocks) <= 1:
        blocks = [line for line in lines if line]
    return [Clause(id=f"clause-{index}", text=block) for index, block in enumerate(blocks, start=1)]

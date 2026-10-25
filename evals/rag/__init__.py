"""Retrieval eval for the handbook (docs/*.md). See docs/rag.md, step 0.

Each question names the doc sections that answer it as `<page>#<slug>`; `<page>#` is the page intro before the
first heading. Slugs follow github-slugger, as the docs site does, so a label is also a working link. `absent`
questions have no answer in the docs: the right result is "not in the docs".
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'
QUESTIONS = Path(__file__).with_name('questions.csv')
HEADING = re.compile(r'^#{2,3} (.+)$')


@dataclass(frozen=True)
class Question:
    id: str
    split: str
    lang: str
    kind: str
    question: str
    answers: tuple[str, ...]


def load_questions(path: Path = QUESTIONS) -> list[Question]:
    with path.open(encoding='utf-8', newline='') as f:
        return [Question(r['id'], r['split'], r['lang'], r['kind'], r['question'],
                         tuple(a for a in r['answers'].split('|') if a)) for r in csv.DictReader(f)]


def _keep(ch: str) -> bool:
    return ch in ' -' or unicodedata.category(ch)[0] in 'LMN' or unicodedata.category(ch) == 'Pc'


def slugs(text: str) -> list[str]:
    """Heading slugs of one page, in order, with github-slugger's -1, -2 suffixes for repeats."""
    seen: dict[str, int] = {}
    out, code = [], False
    for line in text.splitlines():
        if line.startswith('```'):
            code = not code
        m = None if code else HEADING.match(line)
        if not m:
            continue
        base = ''.join(ch for ch in m.group(1).lower() if _keep(ch)).replace(' ', '-')
        slug, n = base, seen.get(base, 0)
        while slug in seen:
            n += 1
            slug = f'{base}-{n}'
        seen[base] = n
        seen[slug] = 0
        out.append(slug)
    return out


def anchors(docs: Path = DOCS) -> set[str]:
    """Every label a question may use: `<page>#` for each page and `<page>#<slug>` for each heading."""
    found = set()
    for page in docs.glob('*.md'):
        found.add(page.stem + '#')
        found.update(f'{page.stem}#{s}' for s in slugs(page.read_text(encoding='utf-8')))
    return found

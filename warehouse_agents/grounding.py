"""Numeric grounding: every number in an answer should come from what the agent actually saw.

Used twice with the same code: as a runtime guardrail (flag, never block) and as the
hallucinated-number metric in evals/. It is a lexical check. It accepts a number when it
matches an evidence value, a percentage/ratio/difference/sum of two values from the same
tool result, or a number in the question or tool contract. It can therefore miss a wrong
number that happens to equal another evidence value, and it does not judge prose claims.
"""

from __future__ import annotations

import itertools
import json
import re

DATE_TIME = re.compile(
    r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?'
    r'|\b\d{1,2}:\d{2}(?::\d{2})?\b'
)
CALENDAR_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
CITATION = re.compile(r'\[[a-z_]+:[^\]\s]*\]')
# Hashes, identifiers and versions carry digits but are not numeric claims: sha256, SHA-256, v2, mv_1, 4828a1ec...
IDENTIFIER = re.compile(
    r'\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,}\b|\b[A-Za-z_]+\d+\w*|\b\w*_\d+\w*'
    r'|\b[A-Z]{2,}-\d+\b'  # SHA-256, UTF-8, ISO-8601
)
LIST_MARKER = re.compile(r'^\s*\d+[.)]\s', re.MULTILINE)
NUMBER = re.compile(r'(?<![\w.,])(\d{1,3}(?:[,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(\s?%)?')
MAX_VALUES_PER_RESULT = 60


DASHES = str.maketrans({c: '-' for c in '\u2010\u2011\u2012\u2013\u2014\u2212'})
# 200\u202f027\u202f899.76: narrow/no-break/thin spaces used as thousands separators.
SPACE_GROUP = re.compile(r'(?<=\d)[\u202f\u00a0\u2009](?=\d{3}(?!\d))')
NUMBER_WORDS = {
    w: float(i)
    for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve'.split())
}


def normalize(text: str) -> str:
    # Models often write 2026\u201110\u201121 with non-breaking hyphens.
    text = SPACE_GROUP.sub('', text).translate(DASHES)
    return text.replace('\u202f', ' ').replace('\u00a0', ' ').replace('\u2009', ' ')


def _strip(text: str) -> tuple[str, list[str]]:
    text = normalize(text)
    dates = DATE_TIME.findall(text)
    for pattern in (DATE_TIME, CITATION, IDENTIFIER, LIST_MARKER):
        text = pattern.sub(' ', text)
    return text, dates


def _interpretations(token: str) -> list[tuple[float, int]]:
    """Return (value, decimals shown) for English and Vietnamese separator conventions."""
    options = []
    if ',' in token and '.' in token:
        decimal = ',' if token.rfind(',') > token.rfind('.') else '.'
        thousands = '.' if decimal == ',' else ','
        whole, frac = token.replace(thousands, '').split(decimal)
        options.append((float(f'{whole}.{frac}'), len(frac)))
    elif ',' in token or '.' in token:
        sep = ',' if ',' in token else '.'
        parts = token.split(sep)
        if len(parts) == 2:
            options.append((float(f'{parts[0]}.{parts[1]}'), len(parts[1])))
        if all(len(p) == 3 for p in parts[1:]):
            options.append((float(''.join(parts)), 0))
    else:
        options.append((float(token), 0))
    return options


def extract_numbers(text: str) -> list[dict]:
    """Numeric claims in free text, ignoring dates, times, list markers, hashes and identifiers."""
    stripped, _ = _strip(text)
    found = []
    for match in NUMBER.finditer(stripped):
        token, percent = match.group(1), bool(match.group(2))
        values = []
        for value, decimals in _interpretations(token):
            values.append((value, decimals))
            if percent:
                values.append((value / 100, decimals + 2))
        found.append({'text': match.group(0).strip(), 'values': values})
    return found


def _leaves(value, dates: set, depth=0):
    """Numeric leaves of a JSON value, including numbers inside strings.

    Year, month and day of any timestamp go to `dates`: an answer may say "21 October 2026",
    but hours and minutes are not accepted as standalone numbers and dates are never derived from.
    """
    if depth > 12:
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, str):
        stripped, found = _strip(value)
        for date in found:
            if CALENDAR_DATE.match(date):
                dates.update(float(p) for p in date[:10].split('-'))
        for item in extract_numbers(stripped):
            for number, _ in item['values']:
                yield number
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item, dates, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item, dates, depth + 1)


def allowed_values(evidence: list[dict], context: list[str] = ()) -> set[float]:
    allowed, dates = set(), set()
    for text in context:
        allowed.update(_leaves(text, dates))
        # "Read last seven days" in a tool description grounds "7 days" in the answer.
        allowed.update(NUMBER_WORDS[w] for w in re.findall(r'[a-z]+', text.lower()) if w in NUMBER_WORDS)
    for call in evidence:
        allowed.update(_leaves(call.get('arguments', {}), dates))
        values = list(dict.fromkeys(_leaves(call.get('result'), dates)))
        allowed.update(values)
        allowed.update(v * 100 for v in values)
        # Simple derivations an analyst would write from one tool result: 3 of 48 -> 6.25%.
        for a, b in itertools.permutations(values[:MAX_VALUES_PER_RESULT], 2):
            allowed.update((a - b, a + b))
            if b:
                allowed.update((a / b, a / b * 100))
    return allowed | dates


def _matches(value: float, decimals: int, allowed: set[float]) -> bool:
    tolerance = 0.5 * 10**-decimals + 1e-9
    for candidate in allowed:
        if abs(abs(value) - abs(candidate)) <= tolerance:
            return True
        if candidate and abs(value - candidate) / abs(candidate) <= 0.002:
            return True
    return False


def check_grounding(answer: str, evidence: list[dict], context: list[str] = ()) -> dict:
    """Split the answer's numbers into grounded and ungrounded against tool evidence and context."""
    allowed = allowed_values(evidence, context)
    numbers = extract_numbers(answer)
    ungrounded = [n['text'] for n in numbers if not any(_matches(v, d, allowed) for v, d in n['values'])]
    return {'total': len(numbers), 'grounded': len(numbers) - len(ungrounded), 'ungrounded': ungrounded}


def contract_context(specs: list[dict]) -> list[str]:
    """Tool descriptions and schemas are in the model's context, so their numbers are grounded."""
    return [json.dumps(spec, ensure_ascii=False) for spec in specs]

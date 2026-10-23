"""Agent skills: task instructions the agent loads on demand (SKILL.md with name/description frontmatter).

The system prompt lists every skill's name and description; the agent calls load_skill(name) to read the full
instructions only when a request matches. Skills are versioned files in this repository, never remote content.
Answers cite [skill:<name>]; a citation is valid only if load_skill returned that skill in the same run.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / 'skills'
NAME = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
CITATION = re.compile(r'\[skill:([a-z0-9-]+)\]')


def parse(text):
    """Frontmatter (name, description) and body of a SKILL.md."""
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.S)
    if not match:
        raise ValueError('SKILL.md needs --- frontmatter ---')
    meta = dict(line.split(':', 1) for line in match.group(1).splitlines() if ':' in line)
    return {k.strip(): v.strip() for k, v in meta.items()}, match.group(2).strip()


@lru_cache(maxsize=1)
def catalog():
    skills = {}
    for path in sorted(ROOT.glob('*/SKILL.md')):
        data = path.read_bytes()
        if len(data) > 16000:
            raise ValueError(f'Skill too large: {path.parent.name}')
        meta, body = parse(data.decode('utf-8'))
        name = meta.get('name', '')
        if (
            name != path.parent.name
            or not NAME.match(name)
            or not 20 <= len(meta.get('description', '')) <= 400
        ):
            raise ValueError(f'Invalid skill frontmatter: {path.parent.name}')
        skills[name] = dict(
            name=name,
            description=meta['description'],
            instructions=body,
            source=f'warehouse_agents/skills/{name}/SKILL.md',
            sha256=hashlib.sha256(data).hexdigest(),
            citation=f'[skill:{name}]',
        )
    return skills


def names():
    return sorted(catalog())


def prompt_section():
    lines = '\n'.join(f'- {s["name"]}: {s["description"]}' for s in catalog().values())
    return (
        'Skills are instructions for specific kinds of request. When a request matches a skill below, call load_skill '
        'with its name in the same step as the first tools you need (not as a step of its own), then follow it, '
        'including its report format, written in the user language (the templates are in English only as a '
        'pattern). Load at most one skill per answer. When you follow a skill, cite it once as '
        '[skill:<name>]. Never cite a skill you did not load in this conversation.\n' + lines
    )


def load(name):
    skill = catalog().get(name)
    if skill is None:
        return dict(status='unavailable', reason='Unknown skill', available=names())
    return dict(status='available', evidence_kind='instructions', **skill)


def validate_citations(answer, evidence):
    """Strip [skill:...] citations of skills not loaded in this run; keep the rest of the answer."""
    loaded = {
        item.get('result', {}).get('name')
        for item in evidence
        if item.get('tool') == 'load_skill' and item.get('result', {}).get('status') == 'available'
    }
    unknown = sorted({f'[skill:{n}]' for n in CITATION.findall(answer) if n not in loaded})
    if unknown:
        # Strip only the unverifiable citations. Discarding the whole answer threw away correct
        # observations in 4 of 29 dev eval cases (see docs/evaluation.md).
        for citation in unknown:
            answer = answer.replace(citation, '[unverified citation removed]')
        answer += f'\n\n> {len(unknown)} skill citation(s) referred to skills not loaded in this answer and were removed.'
    return answer, unknown

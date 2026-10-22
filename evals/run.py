"""Run the Operations agent over the eval cases and write a scored report.

Live:    python -m evals.run --routes groq-primary --split train --dsn postgresql://.../coinsight_eval
Record:  add --record to save model responses and tool results as cassettes
Replay:  python -m evals.run --backend replay --split ci   (no keys, no database, no network)

Live runs execute the real agent, real tools and real SQL against a disposable fixture
database. Replay feeds recorded model responses and tool results back through the same
agent, guardrails and scorer, so CI catches regressions in that code without a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import itertools
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from evals import cases as case_set
from evals import fixtures
from evals.report import write_reports
from evals.scoring import aggregate, score_case

CASSETTES = Path('evals/cassettes')
PRICING = Path('evals/pricing.json')
# Closed local port: tools that need Airflow, Jaeger or HTTP services observe "unreachable".
DEAD_URL = 'http://127.0.0.1:9'
DEAD_DSN = 'postgresql://eval:eval@127.0.0.1:9/coinsight_eval'


class RecordingBackend:
    def __init__(self, inner):
        self.inner, self.responses = inner, []

    async def converse(self, **request):
        response = await self.inner.converse(**request)
        self.responses.append(copy.deepcopy(response))
        return response


class ReplayBackend:
    def __init__(self, responses):
        self.responses = list(responses)

    async def converse(self, **request):
        if not self.responses:
            raise RuntimeError('Replay exhausted: the agent made more model calls than were recorded')
        return copy.deepcopy(self.responses.pop(0))


def replay_tools(names, recorded):
    queues = {name: [e['result'] for e in recorded if e['tool'] == name] for name in names}

    def make(name):
        async def tool(**_arguments):
            if not queues[name]:
                raise RuntimeError(f'Replay has no recorded result for {name}')
            return copy.deepcopy(queues[name].pop(0))

        return tool

    return {name: make(name) for name in names}


async def model_health_unavailable(cutoff=None):
    # The real tool reads live Binance candles; evals must not depend on the market.
    return {
        'status': 'unavailable',
        'reason': 'External market source disabled in the eval environment.',
        'performance_status': 'No prospective forecast ledger is attached; current MAE is unknown.',
    }


def eval_tool_map():
    from warehouse_agents.graph import OPS

    return {**OPS, 'model_health': model_health_unavailable}


def load_routes(path):
    config = json.loads(Path(path).read_text())
    return {route['name']: route for route in config['routes']}


def load_provider_keys(routes, env_file='.env'):
    """Read only the credential variables the routes reference; never DB URLs or other settings."""
    wanted = {r['api_key_env'] for r in routes.values() if r.get('api_key_env')}
    path = Path(env_file)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        name, sep, value = line.strip().partition('=')
        if sep and name in wanted and not os.getenv(name):
            os.environ[name] = value.strip().strip('"\'')


def make_router(route):
    from warehouse_agents.router import Router

    return Router(
        {
            'strategy': 'priority',
            'routes': [route],
            'timeout_seconds': 60,
            'total_timeout_seconds': 120,
            'cooldown_seconds': 1,
        }
    )


def configure_environment(dsn, scenario):
    os.environ['WAREHOUSE_DATABASE_URL'] = DEAD_DSN if scenario == 'db_down' else dsn
    for name in ('AIRFLOW_API_URL', 'FORECAST_AGENT_URL', 'WAREHOUSE_API_URL', 'JAEGER_URL'):
        os.environ[name] = DEAD_URL
    os.environ.pop('AIRFLOW_API_TOKEN', None)


async def run_case(case, reasoner_factory, retries):
    """Run one case; retry rate limits and transient provider failures with backoff."""
    from warehouse_agents.router import RouterUnavailable

    for attempt in itertools.count():
        reasoner, backend = reasoner_factory()
        started = time.perf_counter()
        try:
            result = await reasoner.run(case.question)
            return dict(
                answer=result['answer'],
                evidence=result['evidence'],
                guardrails=result['guardrails'],
                llm_calls=result['llm_calls'],
                usage=result['usage'],
                trace_id=result['trace_id'],
                latency_ms=round((time.perf_counter() - started) * 1000),
                error=None,
                error_type=None,
                responses=getattr(backend, 'responses', None),
            )
        except ValueError as exc:
            if 'Credential-like input' in str(exc):
                return dict(
                    answer='',
                    evidence=[],
                    guardrails={},
                    llm_calls=0,
                    usage={},
                    latency_ms=0,
                    error=None,
                    error_type='input_rejected',
                    responses=[],
                )
            error = f'{type(exc).__name__}: {exc}'
        except RouterUnavailable as exc:
            error = f'provider_unavailable: {json.dumps(exc.attempts)[:500]}'
            if attempt < retries:
                await asyncio.sleep(min(90, 15 * 2**attempt))
                continue
        except Exception as exc:  # the report must show failures, not stop the run
            error = f'{type(exc).__name__}: {str(exc)[:300]}'
        return dict(
            answer='',
            evidence=[],
            guardrails={},
            llm_calls=0,
            usage={},
            latency_ms=None,
            error=error,
            error_type='run_error',
            responses=getattr(backend, 'responses', None),
        )


def context_for(question):
    from warehouse_agents.graph import SPECS, OPS
    from warehouse_agents.grounding import contract_context

    return [question] + contract_context([SPECS[n] for n in OPS])


async def run_route(route_name, route, selected, args):
    from warehouse_agents.graph import Reasoner, OPS

    rows = []
    by_scenario = itertools.groupby(
        sorted(selected, key=lambda c: c.template.scenario), key=lambda c: c.template.scenario
    )
    for scenario, group in by_scenario:
        group = list(group)
        if args.backend == 'live':
            facts = fixtures.build(args.dsn, scenario)
            configure_environment(args.dsn, scenario)
        for case in group:
            cassette_path = CASSETTES / route_name / f'{case.id}.json'
            if args.backend == 'replay':
                if not cassette_path.exists():
                    raise SystemExit(f'No recording {cassette_path}; record it with --record on a live run')
                cassette = json.loads(cassette_path.read_text())
                facts = cassette['facts']

                def factory(cassette=cassette):
                    backend = ReplayBackend(cassette['responses'])
                    return Reasoner(
                        'operations', backend=backend, tool_map=replay_tools(list(OPS), cassette['evidence'])
                    ), backend
            else:

                def factory():
                    backend = RecordingBackend(make_router(route))
                    return Reasoner('operations', backend=backend, tool_map=eval_tool_map()), backend

            run = await run_case(case, factory, args.retries)
            score = score_case(case, run, facts, context_for(case.question))
            if args.backend == 'live' and args.record and not run['error']:
                cassette_path.parent.mkdir(parents=True, exist_ok=True)
                cassette_path.write_text(
                    json.dumps(
                        {
                            'case': case.id,
                            'route': route_name,
                            'facts': facts,
                            'responses': run['responses'],
                            'evidence': run['evidence'],
                            'recorded_at': datetime.now(timezone.utc).isoformat(),
                        },
                        indent=1,
                        default=str,
                        ensure_ascii=False,
                    )
                )
            run.pop('responses', None)
            rows.append(
                dict(
                    case=case.id,
                    template=case.template.id,
                    split=case.split,
                    category=case.template.category,
                    behavior=case.template.behavior,
                    scenario=scenario,
                    question=case.question,
                    route=route_name,
                    facts=facts,
                    **run,
                    score=score,
                )
            )
            mark = 'PASS' if score['passed'] else 'FAIL'
            print(
                f'  {mark} {case.id:32} {run.get("latency_ms") or 0:>6} ms  {score.get("error") or ""}'[:160],
                flush=True,
            )
            if args.backend == 'live' and args.pace:
                await asyncio.sleep(args.pace)
    return rows


def agent_version():
    """Tie results to the exact code: git commit, uncommitted changes, and a hash of the agent's prompt and tools."""
    import hashlib
    import subprocess

    from warehouse_agents import skills
    from warehouse_agents.graph import SPECS

    def git(*command):
        return subprocess.run(['git', *command], capture_output=True, text=True).stdout.strip()

    agent = json.dumps({'specs': SPECS, 'skills': skills.catalog()}, sort_keys=True, default=str)
    agent += Path('warehouse_agents/graph.py').read_text()
    return dict(
        git_commit=git('rev-parse', 'HEAD'),
        git_dirty=bool(
            git('status', '--porcelain', '--', 'warehouse_agents', 'evals/cases.py', 'evals/scoring.py')
        ),
        agent_sha256=hashlib.sha256(agent.encode()).hexdigest()[:16],
    )


async def main_async(args):
    selected = case_set.select(args.split)
    if args.cases:
        wanted = set(args.cases.split(','))
        selected = [c for c in selected if c.id in wanted or c.template.id in wanted]
    if args.limit:
        selected = selected[: args.limit]
    if args.backend == 'live':
        if not args.dsn:
            raise SystemExit(
                'Live runs need --dsn (or EVAL_DATABASE_URL) for a disposable coinsight_eval database'
            )
        routes = load_routes(args.routes_file)
        load_provider_keys(routes)
        names = args.routes.split(',') if args.routes else list(routes)
    else:
        names = (
            args.routes.split(',')
            if args.routes
            else sorted(p.name for p in CASSETTES.iterdir() if p.is_dir())
        )
        routes = {name: None for name in names}
    pricing = json.loads(PRICING.read_text()) if PRICING.exists() else {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summaries = {}
    for name in names:
        print(f'route {name}: {len(selected)} cases ({args.backend})', flush=True)
        rows = await run_route(name, routes[name], selected, args)
        model = routes[name]['model'] if routes[name] else None
        summaries[name] = dict(model=model, **aggregate(rows, pricing.get(model) if model else None))
        with (out / f'results-{name}.jsonl').open('w') as handle:
            for row in rows:
                handle.write(json.dumps(row, default=str, ensure_ascii=False) + '\n')
    meta = dict(
        split=args.split,
        backend=args.backend,
        generated_at=datetime.now(timezone.utc).isoformat(),
        cases=len(selected),
        **agent_version(),
    )
    write_reports(out, meta, summaries)
    print(json.dumps(summaries, indent=1))
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--backend', choices=('live', 'replay'), default='live')
    parser.add_argument('--routes', help='comma-separated route names (default: all in the routes file)')
    parser.add_argument('--routes-file', default='evals/routes.json')
    parser.add_argument('--split', choices=('train', 'val', 'test', 'ci', 'all'), default='train')
    parser.add_argument('--cases', help='comma-separated case or template ids')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--dsn', default=os.getenv('EVAL_DATABASE_URL'))
    parser.add_argument('--record', action='store_true', help='save cassettes for replay')
    parser.add_argument('--retries', type=int, default=3)
    parser.add_argument('--pace', type=float, default=0.0, help='seconds to wait between live cases')
    parser.add_argument('--out', default='evals/reports/latest')
    parser.add_argument('--min-pass-rate', type=float, help='exit non-zero below this pass rate (CI gate)')
    args = parser.parse_args()
    summaries = asyncio.run(main_async(args))
    if args.min_pass_rate is not None:
        worst = min(s['pass_rate'] or 0 for s in summaries.values())
        if worst < args.min_pass_rate:
            raise SystemExit(f'pass rate {worst} below gate {args.min_pass_rate}')


if __name__ == '__main__':
    main()

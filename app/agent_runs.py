"""The agent run log (meta.agent_run): every answer is recorded with its steps, and a thread's earlier turns
are read back as conversation history for the next question."""

import json
import os
import time
import uuid
from contextlib import closing

import psycopg2
from fastapi import HTTPException

try:
    from .desk_commands import CommandRequest, command
except ImportError:
    from desk_commands import CommandRequest, command

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://crypto:crypto@localhost:5432/crypto_dw')
HISTORY_TURNS = 4


def query(sql, params=(), fetch=True):
    with closing(psycopg2.connect(DATABASE_URL)) as conn, conn, conn.cursor() as cur:
        cur.execute(sql, params)
        if not fetch:
            return cur.rowcount
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def thread_history(user_key, thread_id):
    """The thread's last answered turns, oldest first, as [{'role', 'text'}]."""
    rows = query(
        """select question, answer from meta.agent_run
           where user_key = %s and thread_id = %s and status = 'ok' and command in ('trade', 'sre')
           order by created_at desc limit %s""",
        (user_key, str(thread_id), HISTORY_TURNS),
    )
    history = []
    for row in reversed(rows):
        history += [
            {'role': 'user', 'text': row['question']},
            {'role': 'assistant', 'text': row['answer'] or ''},
        ]
    return history


def record(run_id, user_key, thread_id, request, started, result=None, error=None):
    result = result or {}
    usage = result.get('usage') or {}
    models = sorted({(s.get('model') or {}).get('model') for s in result.get('steps', []) if s.get('model')})
    query(
        """insert into meta.agent_run (run_id, user_key, thread_id, command, symbol, question, model_requested,
               answer, status, error, models, llm_calls, input_tokens, output_tokens, latency_ms, trace_id,
               steps, evidence, guardrails)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            str(run_id),
            user_key,
            str(thread_id),
            request.command,
            request.symbol,
            request.question,
            request.model,
            result.get('answer'),
            'error' if error else 'ok',
            error,
            models,
            int(result.get('llm_calls') or 0),
            int(usage.get('inputTokens') or 0),
            int(usage.get('outputTokens') or 0),
            round((time.perf_counter() - started) * 1000),
            result.get('trace_id'),
            json.dumps(result.get('steps', []), default=str),
            json.dumps(result.get('evidence', []), default=str),
            json.dumps(result.get('guardrails'), default=str) if result.get('guardrails') else None,
        ),
        fetch=False,
    )


def run(request: CommandRequest, user_key):
    """Answer one Desk command in its thread and log it, success or failure."""
    thread_id = request.thread_id or uuid.uuid4()
    history = thread_history(user_key, thread_id) if request.command in ('trade', 'sre') else []
    run_id, started = uuid.uuid4(), time.perf_counter()
    try:
        result = command(request, user_key, history)
    except HTTPException as exc:
        record(run_id, user_key, thread_id, request, started, error=str(exc.detail)[:500])
        raise
    record(run_id, user_key, thread_id, request, started, result=result)
    return {**result, 'run_id': str(run_id), 'thread_id': str(thread_id)}


def threads(user_key, limit=50):
    return query(
        """select thread_id, min(created_at) as started_at, max(created_at) as updated_at, count(*) as turns,
                  (array_agg(question order by created_at))[1] as title
           from meta.agent_run where user_key = %s
           group by thread_id order by max(created_at) desc limit %s""",
        (user_key, limit),
    )


def thread(user_key, thread_id):
    return query(
        """select run_id, created_at, command, symbol, question, model_requested, answer, status, error, models,
                  llm_calls, input_tokens, output_tokens, latency_ms, trace_id, steps, evidence, guardrails
           from meta.agent_run where user_key = %s and thread_id = %s order by created_at""",
        (user_key, str(thread_id)),
    )


def delete_thread(user_key, thread_id):
    return query(
        'delete from meta.agent_run where user_key = %s and thread_id = %s',
        (user_key, str(thread_id)),
        fetch=False,
    )

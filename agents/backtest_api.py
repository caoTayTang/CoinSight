"""Small authenticated async job API around the causal policy backtester."""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
import os
from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.requests import Request
from starlette.responses import JSONResponse

from pipeline.decision.trading.historical_backtest import HistoricalPolicyBacktestRunner
from pipeline.decision.trading.policy_store import PolicyStore


class BacktestJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^(BTC|ETH)$")
    policy_config: dict
    start: str | None = None
    end: str | None = None
    initial_cash_usdt: float = Field(default=100_000.0, gt=0, le=100_000_000)
    performance_days: int = Field(default=30, ge=7, le=365)
    market_days: int = Field(default=30, ge=7, le=365)
    trend_hours: int = Field(default=168, ge=24, le=1000)

    @model_validator(mode="after")
    def valid_locked_range(self):
        minimum = date(2026, 2, 1)
        try:
            start = date.fromisoformat(self.start) if self.start else minimum
            end = date.fromisoformat(self.end) if self.end else None
        except ValueError:
            raise ValueError("backtest dates must use YYYY-MM-DD") from None
        if start < minimum or (end is not None and end < minimum):
            raise ValueError("backtest dates before 2026-02-01 are locked")
        if end is not None and end <= start:
            raise ValueError("backtest end must be after start (end is exclusive)")
        self.start = start.isoformat()
        return self


_JOBS: dict[str, dict] = {}
_LOCK = Lock()


def _authorized(request: Request) -> bool:
    expected = os.getenv("INTERNAL_SERVICE_TOKEN", "")
    return not expected or request.headers.get("authorization") == f"Bearer {expected}"


def _public(job: dict) -> dict:
    return {key: value for key, value in job.items() if not key.startswith("_")}


async def create_backtest(request: Request):
    if not _authorized(request):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    try:
        payload = BacktestJobRequest.model_validate(await request.json())
        policy = PolicyStore().validate(payload.policy_config)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    job_id = str(uuid4())
    job = {
        "job_id": job_id, "status": "queued", "progress": 0.0,
        "completed_steps": 0, "total_steps": 0,
        "created_at": datetime.now(UTC).isoformat(), "result": None, "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = job
    asyncio.create_task(_run(job_id, payload, policy))
    return JSONResponse(_public(job), status_code=202)


async def get_backtest(request: Request):
    if not _authorized(request):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    with _LOCK:
        job = _JOBS.get(request.path_params["job_id"])
        response = _public(job) if job else None
    if response is None:
        return JSONResponse({"detail": "backtest job not found"}, status_code=404)
    return JSONResponse(response)


async def _run(job_id: str, payload: BacktestJobRequest, policy: dict) -> None:
    loop = asyncio.get_running_loop()

    def progress(done: int, total: int, cutoff) -> None:
        def update():
            with _LOCK:
                _JOBS[job_id].update(
                    status="running", completed_steps=done, total_steps=total,
                    progress=done / total if total else 0.0,
                    current_cutoff=cutoff.isoformat(),
                )
        loop.call_soon_threadsafe(update)

    def stage(value: str) -> None:
        def update():
            with _LOCK:
                _JOBS[job_id]["phase"] = value
        loop.call_soon_threadsafe(update)

    def execute():
        runner = HistoricalPolicyBacktestRunner(
            policy,
            bundle_root=os.getenv("DAILY_FORECAST_BUNDLE_ROOT", "/models/daily-forecast"),
            snapshot_root=os.getenv("FORECAST_SNAPSHOT_ROOT", "/data/forecasting/snapshots"),
            device="cpu",
        )
        result, _ = runner.run(
            payload.symbol, start=payload.start, end=payload.end,
            initial_cash_usdt=payload.initial_cash_usdt,
            performance_days=payload.performance_days, market_days=payload.market_days,
            trend_hours=payload.trend_hours, progress=progress, stage=stage,
        )
        return result

    try:
        with _LOCK:
            _JOBS[job_id]["status"] = "running"
        result = await asyncio.to_thread(execute)
        with _LOCK:
            _JOBS[job_id].update(
                status="completed", progress=1.0, result=result,
                finished_at=datetime.now(UTC).isoformat(),
            )
    except Exception as exc:
        with _LOCK:
            _JOBS[job_id].update(
                status="failed", error=f"{type(exc).__name__}: {exc}",
                finished_at=datetime.now(UTC).isoformat(),
            )

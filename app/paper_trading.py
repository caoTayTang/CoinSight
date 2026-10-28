"""Authenticated paper portfolio API; forecast evidence comes from the internal Desk gateway."""
from __future__ import annotations

from functools import lru_cache
from datetime import date, datetime
import json
import os
from threading import Lock
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
import psycopg2

try:
    from .auth import User, current_user
    from .desk_commands import CommandRequest, command
except ImportError:
    from auth import User, current_user
    from desk_commands import CommandRequest, command

from pipeline.decision.trading.decision_service import TradeDecisionService
from pipeline.decision.trading.repository import PaperTradingRepository

router = APIRouter(prefix="/v1/paper", tags=["paper-trading"])


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Paper portfolio", min_length=1, max_length=80)
    initial_cash_usdt: float = Field(default=100_000.0, ge=100, le=100_000_000)


class DecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: Literal["BTC", "ETH"]


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_source_candle_time: datetime


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_id: UUID


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict


class BacktestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: Literal["BTC", "ETH"]
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


POLICY_FIELDS = [
    {"name": "min_performance_samples", "label": "Minimum performance samples", "min": 7, "max": 365, "step": 1,
     "help": "Minimum recent scored predictions required before BUY/SELL is allowed."},
    {"name": "trade_threshold", "label": "Trade threshold", "min": 0, "max": 1, "step": 0.01,
     "help": "Minimum absolute signed support score. Lower values trade more often and accept weaker evidence."},
    {"name": "max_asset_fraction", "label": "Maximum asset allocation", "min": 0, "max": 1, "step": 0.01,
     "help": "Largest fraction of portfolio equity that may be allocated to one coin."},
    {"name": "max_order_fraction", "label": "Maximum order size", "min": 0, "max": 1, "step": 0.01,
     "help": "Largest fraction of current equity one BUY or SELL may change."},
    {"name": "max_annualized_volatility", "label": "Volatility warning threshold", "min": 0.01, "max": 10, "step": 0.05,
     "help": "Above this annualized volatility, policy support is reduced by 30%."},
    {"name": "max_market_drawdown_fraction", "label": "Market drawdown warning", "min": 0, "max": 1, "step": 0.01,
     "help": "A deeper market drawdown reduces policy support by 30%."},
    {"name": "max_portfolio_drawdown_fraction", "label": "Portfolio drawdown exit", "min": 0, "max": 1, "step": 0.01,
     "help": "At this portfolio drawdown, target allocation becomes zero (risk exit)."},
    {"name": "rebalance_tolerance", "label": "Rebalance tolerance", "min": 0, "max": 1, "step": 0.005,
     "help": "Allocation changes smaller than this are HOLD to avoid unnecessary trades."},
    {"name": "slippage_bps", "label": "Simulated slippage (bps)", "min": 0, "max": 100, "step": 0.5,
     "help": "Adverse simulated fill movement; 10 bps equals 0.10%. No exchange fee is modeled."},
    {"name": "max_price_age_seconds", "label": "Maximum live price age", "min": 30, "max": 3600, "step": 30,
     "help": "Reject an order preview when its latest closed-minute execution price is older than this."},
]

_BACKTEST_OWNERS: dict[str, str] = {}
_BACKTEST_LOCK = Lock()


def _user(user: User = Depends(current_user)) -> User:
    if user.anonymous:
        raise HTTPException(401, "Sign in to use persistent paper trading.")
    return user


@lru_cache(maxsize=1)
def repository() -> PaperTradingRepository:
    return PaperTradingRepository()


@lru_cache(maxsize=1)
def service() -> TradeDecisionService:
    return TradeDecisionService(repository())


def _safe(callable_):
    try:
        return callable_()
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except psycopg2.IntegrityError:
        raise HTTPException(409, "Paper-trading state conflicts with an existing record.") from None


def _prediction_call(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    base = os.getenv("PREDICTION_AGENT_URL", "http://127.0.0.1:8011").rstrip("/")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    token = os.getenv("WAREHOUSE_AGENT_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read(8_000_000))
    except HTTPError as exc:
        detail = exc.read(16_384).decode("utf-8", "replace")
        raise HTTPException(exc.code, f"Prediction service rejected backtest: {detail}") from None
    except (URLError, TimeoutError) as exc:
        raise HTTPException(503, f"Prediction service unavailable: {exc}") from None


@router.post("/portfolios")
def create_portfolio(payload: PortfolioCreate, user: User = Depends(_user)) -> dict:
    return _safe(lambda: repository().create_portfolio(user.key, payload.name, payload.initial_cash_usdt))


@router.get("/portfolios")
def list_portfolios(user: User = Depends(_user)) -> dict:
    return {"portfolios": _safe(lambda: repository().list_portfolios(user.key))}


@router.get("/policy")
def get_policy(user: User = Depends(_user)) -> dict:
    result = _safe(lambda: service().active_policy(user.key))
    return {**result, "fields": POLICY_FIELDS}


@router.put("/policy")
def update_policy(payload: PolicyUpdate, user: User = Depends(_user)) -> dict:
    result = _safe(lambda: service().save_policy(user.key, payload.config))
    return {**result, "fields": POLICY_FIELDS}


@router.delete("/policy")
def reset_policy(user: User = Depends(_user)) -> dict:
    result = _safe(lambda: service().reset_policy(user.key))
    return {**result, "fields": POLICY_FIELDS}


@router.post("/backtests", status_code=202)
def create_backtest(payload: BacktestCreate, user: User = Depends(_user)) -> dict:
    validated = _safe(lambda: service().normalize_policy(payload.policy_config))
    request_payload = payload.model_dump()
    request_payload["policy_config"] = validated
    result = _prediction_call("/policy-backtests", "POST", request_payload)
    with _BACKTEST_LOCK:
        _BACKTEST_OWNERS[result["job_id"]] = user.key
    return result


@router.get("/backtests/{job_id}")
def get_backtest(job_id: UUID, user: User = Depends(_user)) -> dict:
    with _BACKTEST_LOCK:
        owner = _BACKTEST_OWNERS.get(str(job_id))
    if owner != user.key:
        raise HTTPException(404, "Backtest job not found.")
    return _prediction_call(f"/policy-backtests/{job_id}")


@router.get("/portfolios/{portfolio_id}")
def get_portfolio(portfolio_id: UUID, user: User = Depends(_user)) -> dict:
    return _safe(lambda: repository().portfolio(user.key, str(portfolio_id)))


@router.post("/portfolios/{portfolio_id}/decisions")
def create_decision(
    portfolio_id: UUID, payload: DecisionCreate, user: User = Depends(_user)
) -> dict:
    forecast_reply = command(CommandRequest(command="predict", symbol=payload.symbol), user.key)
    support = forecast_reply.get("evidence")
    if not isinstance(support, dict) or support.get("status") != "ready":
        raise HTTPException(503, "Forecast support is unavailable; no paper decision was created.")
    return _safe(lambda: service().create(user.key, str(portfolio_id), support))


@router.get("/portfolios/{portfolio_id}/decisions/latest")
def latest_decision(
    portfolio_id: UUID,
    symbol: Literal["BTC", "ETH"] = Query("BTC"),
    user: User = Depends(_user),
) -> dict:
    result = _safe(lambda: repository().latest_decision(user.key, str(portfolio_id), symbol))
    return {"decision": result}


@router.post("/portfolios/{portfolio_id}/orders/preview")
def preview_order(
    portfolio_id: UUID, payload: PreviewRequest, user: User = Depends(_user)
) -> dict:
    return _safe(lambda: service().preview(user.key, str(portfolio_id), str(payload.decision_id)))


@router.post("/portfolios/{portfolio_id}/orders")
def execute_order(
    portfolio_id: UUID, payload: OrderRequest, user: User = Depends(_user)
) -> dict:
    return _safe(lambda: service().execute(
        user.key, str(portfolio_id), str(payload.decision_id), payload.idempotency_key,
        payload.expected_source_candle_time,
    ))


@router.get("/portfolios/{portfolio_id}/orders")
def list_orders(
    portfolio_id: UUID, limit: int = Query(100, ge=1, le=500), user: User = Depends(_user)
) -> dict:
    return {"orders": _safe(lambda: repository().orders(user.key, str(portfolio_id), limit))}


@router.get("/portfolios/{portfolio_id}/equity")
def equity_curve(
    portfolio_id: UUID, limit: int = Query(1000, ge=1, le=5000), user: User = Depends(_user)
) -> dict:
    return {"equity": _safe(lambda: repository().equity_curve(user.key, str(portfolio_id), limit))}


@router.get("/portfolios/{portfolio_id}/analytics")
def trade_analytics(
    portfolio_id: UUID, limit: int = Query(500, ge=1, le=2000), user: User = Depends(_user)
) -> dict:
    return _safe(lambda: repository().trade_analytics(user.key, str(portfolio_id), limit))


@router.get("/market/{symbol}/candles")
def daily_candles(
    symbol: Literal["BTC", "ETH"],
    interval: Literal["1d", "1h"] = Query("1d"),
    limit: int = Query(90, ge=20, le=4000),
    user: User = Depends(_user),
) -> dict:
    return {
        "interval": interval,
        "candles": _safe(lambda: repository().market_candles(symbol, interval, limit)),
    }

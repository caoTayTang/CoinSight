"""PostgreSQL repository and atomic long-only paper fills."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import os
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, Json

from .contracts import OrderPreview, PortfolioState


def _float(value, default=0.0) -> float:
    return default if value is None else float(value)


class PaperTradingRepository:
    def __init__(self, dsn: str | None = None, connect_fn=None):
        self.dsn = dsn or os.getenv(
            "DATABASE_URL",
            os.getenv("WAREHOUSE_DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw"),
        )
        self.connect_fn = connect_fn or psycopg2.connect

    def _connect(self):
        return self.connect_fn(self.dsn)

    def create_portfolio(self, user_key: str, name: str, initial_cash_usdt: float) -> dict:
        if user_key.startswith("a_"):
            raise ValueError("anonymous users cannot create persistent paper portfolios")
        name = str(name).strip()
        cash = float(initial_cash_usdt)
        if not name or len(name) > 80 or not 100 <= cash <= 100_000_000:
            raise ValueError("name or initial cash is outside the allowed range")
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """insert into paper.portfolio(user_key,name,initial_cash_usdt)
                   values (%s,%s,%s) returning *""",
                (user_key, name, cash),
            )
            return self._serialize(cur.fetchone())

    def list_portfolios(self, user_key: str) -> list[dict]:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "select * from paper.portfolio where user_key=%s order by created_at",
                (user_key,),
            )
            return [self._summary(cur, row) for row in cur.fetchall()]

    def portfolio(self, user_key: str, portfolio_id: str) -> dict:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            row = self._portfolio_row(cur, user_key, portfolio_id)
            return self._summary(cur, row)

    def active_policy(self, user_key: str, fallback: dict) -> dict:
        """Return the user's validated override, or the checked-in default."""
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "select config,updated_at from paper.user_policy where user_key=%s",
                (user_key,),
            )
            row = cur.fetchone()
            return {
                "source": "user" if row else "default",
                "config": self._serialize(row["config"] if row else fallback),
                "updated_at": self._serialize(row["updated_at"]) if row else None,
            }

    def save_policy(self, user_key: str, config: dict) -> dict:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """insert into paper.user_policy(user_key,policy_name,config,config_sha256)
                   values (%s,'daily_quantile_v1',%s,%s)
                   on conflict (user_key) do update set
                     config=excluded.config,config_sha256=excluded.config_sha256,updated_at=now()
                   returning config,updated_at""",
                (user_key, Json(config), config["sha256"]),
            )
            row = cur.fetchone()
            return {"source": "user", "config": row["config"], "updated_at": row["updated_at"]}

    def reset_policy(self, user_key: str, fallback: dict) -> dict:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("delete from paper.user_policy where user_key=%s", (user_key,))
        return {"source": "default", "config": fallback, "updated_at": None}

    def state(self, user_key: str, portfolio_id: str, symbol: str) -> PortfolioState:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            row = self._portfolio_row(cur, user_key, portfolio_id)
            states, cash, realized = self._replay(cur, portfolio_id, _float(row["initial_cash_usdt"]))
            prices = self._latest_prices(cur, tuple(set(states) | {symbol}))
            equity = cash + sum(value["quantity"] * prices[key]["price"] for key, value in states.items())
            item = states.get(symbol, {"quantity": 0.0, "average_entry": None})
            price = prices[symbol]
            value = item["quantity"] * price["price"]
            peak = self._equity_peak(cur, portfolio_id, _float(row["initial_cash_usdt"]))
            drawdown = min(0.0, equity / peak - 1.0) if peak > 0 else 0.0
            return PortfolioState(
                portfolio_id=str(row["portfolio_id"]), user_key=user_key,
                initial_cash_usdt=_float(row["initial_cash_usdt"]), cash_usdt=cash,
                equity_usdt=equity, realized_pnl_usdt=realized, maximum_drawdown=drawdown,
                symbol=symbol, position_quantity=item["quantity"],
                average_entry_price_usdt=item["average_entry"],
                current_price_usdt=price["price"], position_value_usdt=value,
                position_fraction=value / equity if equity > 0 else 0.0,
                price_observed_at=price["observed_at"],
            )

    def save_decision(
        self,
        user_key: str,
        portfolio_id: str,
        support: dict,
        policy: dict,
        draft,
        evidence_sha256: str,
        execution: dict,
    ) -> dict:
        forecast, model = support["forecast"], support["model"]
        cutoff = support["data_readiness"]["daily_cutoff"]
        target_close = forecast["target_close"]
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._portfolio_row(cur, user_key, portfolio_id)
            cur.execute(
                """insert into paper.decision(
                    portfolio_id,symbol,cutoff,target_close,policy_id,policy_version,policy_sha256,
                    policy_config,
                    model_id,model_version,action,support_score,signed_score,target_position_fraction,
                    order_notional_usdt,executable,reasons,risk_flags,components,evidence,evidence_sha256,
                    valid_until,evaluated_at,execution_price_usdt,execution_price_observed_at,
                    execution_price_age_seconds,current_position_fraction)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s,%s)
                   returning *""",
                (
                    portfolio_id, support["symbol"], cutoff, target_close,
                    policy["policy_id"], policy["version"], policy["sha256"],
                    Json(policy),
                    model["model_id"], model["model_version"], draft.action,
                    draft.support_score, draft.signed_score, draft.target_position_fraction,
                    draft.order_notional_usdt, draft.executable, Json(list(draft.reasons)),
                    Json(list(draft.risk_flags)), Json(draft.components), Json(support),
                    evidence_sha256, target_close, execution["evaluated_at"],
                    execution["price_usdt"], execution["price_observed_at"],
                    execution["price_age_seconds"], execution["current_position_fraction"],
                ),
            )
            return self._serialize(cur.fetchone())

    def decision(self, user_key: str, portfolio_id: str, decision_id: str) -> dict:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._portfolio_row(cur, user_key, portfolio_id)
            cur.execute(
                "select * from paper.decision where decision_id=%s and portfolio_id=%s",
                (decision_id, portfolio_id),
            )
            row = cur.fetchone()
            if not row:
                raise LookupError("paper decision not found")
            return self._serialize(row)

    def latest_decision(self, user_key: str, portfolio_id: str, symbol: str) -> dict | None:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._portfolio_row(cur, user_key, portfolio_id)
            cur.execute(
                """select * from paper.decision where portfolio_id=%s and symbol=%s
                   order by evaluated_at desc, created_at desc limit 1""",
                (portfolio_id, symbol),
            )
            row = cur.fetchone()
            return self._serialize(row) if row else None

    def preview(
        self, user_key: str, portfolio_id: str, decision_id: str,
        slippage_bps: float, max_price_age_seconds: int = 300,
    ) -> OrderPreview:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            portfolio = self._portfolio_row(cur, user_key, portfolio_id)
            decision = self._decision_row(cur, portfolio_id, decision_id)
            return self._preview(
                cur, portfolio, decision, float(slippage_bps), int(max_price_age_seconds)
            )

    def execute(
        self, user_key: str, portfolio_id: str, decision_id: str,
        idempotency_key: str, slippage_bps: float,
        expected_source_candle_time: datetime, max_price_age_seconds: int = 300,
    ) -> dict:
        if not 8 <= len(idempotency_key) <= 100:
            raise ValueError("idempotency_key must contain 8..100 characters")
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "select * from paper.portfolio where portfolio_id=%s and user_key=%s for update",
                (portfolio_id, user_key),
            )
            portfolio = cur.fetchone()
            if not portfolio:
                raise LookupError("paper portfolio not found")
            cur.execute(
                """select o.*, f.* from paper.paper_order o left join paper.fill f using(order_id)
                   where o.portfolio_id=%s and o.idempotency_key=%s""",
                (portfolio_id, idempotency_key),
            )
            existing = cur.fetchone()
            if existing:
                return self._serialize(existing)
            decision = self._decision_row(cur, portfolio_id, decision_id)
            preview = self._preview(
                cur, portfolio, decision, float(slippage_bps), int(max_price_age_seconds)
            )
            if (
                expected_source_candle_time.tzinfo is None
                or expected_source_candle_time.utcoffset() is None
            ):
                raise ValueError("expected_source_candle_time must include a timezone")
            expected = expected_source_candle_time.astimezone(UTC)
            observed = preview.source_candle_time.astimezone(UTC)
            if observed != expected:
                raise ValueError("execution price changed since preview; preview the order again")
            cur.execute(
                """insert into paper.paper_order(
                    decision_id,portfolio_id,symbol,side,requested_notional_usdt,idempotency_key,status)
                   values (%s,%s,%s,%s,%s,%s,'FILLED') returning order_id,created_at""",
                (decision_id, portfolio_id, preview.symbol, preview.side, preview.notional_usdt, idempotency_key),
            )
            order = cur.fetchone()
            states, _, realized_before = self._replay(cur, portfolio_id, _float(portfolio["initial_cash_usdt"]))
            before = states.get(preview.symbol, {"quantity": 0.0, "average_entry": None})
            if preview.side == "BUY":
                new_average = (
                    (before["quantity"] * (before["average_entry"] or 0.0) + preview.notional_usdt)
                    / preview.position_quantity_after
                )
                realized = realized_before
            else:
                new_average = before["average_entry"] if preview.position_quantity_after > 1e-12 else None
                realized = realized_before + preview.quantity * (
                    preview.fill_price_usdt - (before["average_entry"] or preview.fill_price_usdt)
                )
            equity_after = preview.cash_after_usdt
            for symbol in set(states) | {preview.symbol}:
                item = states.get(symbol, {"quantity": 0.0})
                quantity = preview.position_quantity_after if symbol == preview.symbol else item["quantity"]
                price = preview.fill_price_usdt if symbol == preview.symbol else self._latest_prices(cur, (symbol,))[symbol]["price"]
                equity_after += quantity * price
            peak = self._equity_peak(cur, portfolio_id, _float(portfolio["initial_cash_usdt"]))
            drawdown = min(0.0, equity_after / max(peak, equity_after) - 1.0)
            cur.execute(
                """insert into paper.fill(
                    order_id,quantity,market_price_usdt,fill_price_usdt,notional_usdt,slippage_bps,
                    source,source_candle_time,cash_after_usdt,position_quantity_after,
                    average_entry_after_usdt,realized_pnl_usdt,equity_after_usdt)
                   values (%s,%s,%s,%s,%s,%s,'dw.fact_candle_minute_live',%s,%s,%s,%s,%s,%s)
                   returning *""",
                (
                    order["order_id"], preview.quantity, preview.market_price_usdt,
                    preview.fill_price_usdt, preview.notional_usdt, preview.slippage_bps,
                    preview.source_candle_time, preview.cash_after_usdt,
                    preview.position_quantity_after, new_average, realized, equity_after,
                ),
            )
            fill = cur.fetchone()
            cur.execute(
                """insert into paper.equity_snapshot(
                    portfolio_id,observed_at,cash_usdt,positions_value_usdt,equity_usdt,
                    realized_pnl_usdt,drawdown,source)
                   values (%s,%s,%s,%s,%s,%s,%s,'paper_fill') on conflict do nothing""",
                (
                    portfolio_id, fill["executed_at"], preview.cash_after_usdt,
                    equity_after - preview.cash_after_usdt, equity_after, realized, drawdown,
                ),
            )
            return self._serialize({**order, **fill, "side": preview.side, "symbol": preview.symbol})

    def orders(self, user_key: str, portfolio_id: str, limit: int = 100) -> list[dict]:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._portfolio_row(cur, user_key, portfolio_id)
            cur.execute(
                """select * from paper.trade_history where portfolio_id=%s
                   order by executed_at desc nulls last limit %s""",
                (portfolio_id, min(max(int(limit), 1), 500)),
            )
            return [self._serialize(row) for row in cur.fetchall()]

    def equity_curve(self, user_key: str, portfolio_id: str, limit: int = 1000) -> list[dict]:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._portfolio_row(cur, user_key, portfolio_id)
            cur.execute(
                """select observed_at,cash_usdt,positions_value_usdt,equity_usdt,
                          realized_pnl_usdt,drawdown
                   from paper.equity_snapshot where portfolio_id=%s
                   order by observed_at limit %s""",
                (portfolio_id, min(max(int(limit), 1), 5000)),
            )
            return [self._serialize(row) for row in cur.fetchall()]

    def market_candles(
        self, symbol: str, interval: str = "1d", limit: int = 90
    ) -> list[dict]:
        symbol = str(symbol).upper()
        if symbol not in ("BTC", "ETH"):
            raise ValueError("candles support BTC and ETH only")
        if interval not in ("1d", "1h"):
            raise ValueError("candle interval must be 1d or 1h")
        if interval == "1d":
            table, opened, maximum = "dw.fact_ohlcv_daily", "d.full_date::timestamptz", 730
        else:
            table, opened, maximum = "dw.fact_ohlcv_hourly", "f.open_time", 4000
        query = f"""select {opened} as open_time,
                          f.open_price::float8 as open_price,
                          f.high_price::float8 as high_price,
                          f.low_price::float8 as low_price,
                          f.close_price::float8 as close_price
                   from {table} f
                   join dw.dim_asset a using(asset_key)
                   join dw.dim_source s using(source_key)
                   {'join dw.dim_date d using(date_key)' if interval == '1d' else ''}
                   where a.symbol=%s and s.source_code='binance'
                   order by open_time desc limit %s"""
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (symbol, min(max(int(limit), 20), maximum)))
            rows = [self._serialize(row) for row in reversed(cur.fetchall())]
            return [{**row, "interval": interval} for row in rows]

    def daily_candles(self, symbol: str, limit: int = 90) -> list[dict]:
        return self.market_candles(symbol, "1d", limit)

    def trade_analytics(self, user_key: str, portfolio_id: str, limit: int = 500) -> dict:
        """Score accepted fills against their next-day target close."""
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            portfolio = self._portfolio_row(cur, user_key, portfolio_id)
            cur.execute(
                """select o.order_id,o.decision_id,o.symbol,o.side,f.quantity::float8,
                          f.fill_price_usdt::float8,f.notional_usdt::float8,f.executed_at,
                          (d.evidence #>> '{forecast,reference_close_usdt}')::float8 as reference_close_usdt,
                          actual.close_price::float8 as actual_target_close_usdt
                   from paper.paper_order o
                   join paper.fill f using(order_id)
                   join paper.decision d using(decision_id)
                   left join lateral (
                     select fd.close_price
                     from dw.fact_ohlcv_daily fd
                     join dw.dim_asset a using(asset_key)
                     join dw.dim_source s using(source_key)
                     join dw.dim_date dd using(date_key)
                     where a.symbol=o.symbol and s.source_code='binance'
                       and dd.full_date=((d.evidence #>> '{forecast,target_open}')::timestamptz
                                         at time zone 'UTC')::date
                     limit 1
                   ) actual on true
                   where o.portfolio_id=%s and o.status='FILLED'
                   order by f.executed_at desc limit %s""",
                (portfolio_id, min(max(int(limit), 1), 2000)),
            )
            rows = [self._serialize(row) for row in cur.fetchall()]
            summary = self._summary(cur, portfolio)
        return summarize_trade_outcomes(rows, summary)

    def _summary(self, cur, portfolio: dict) -> dict:
        states, cash, realized = self._replay(cur, str(portfolio["portfolio_id"]), _float(portfolio["initial_cash_usdt"]))
        prices = self._latest_prices(cur, tuple(states)) if states else {}
        positions = []
        value = 0.0
        for symbol, state in sorted(states.items()):
            current = prices[symbol]
            position_value = state["quantity"] * current["price"]
            value += position_value
            positions.append({
                "symbol": symbol, "quantity": state["quantity"],
                "average_entry_price_usdt": state["average_entry"],
                "current_price_usdt": current["price"], "position_value_usdt": position_value,
                "unrealized_pnl_usdt": position_value - state["quantity"] * (state["average_entry"] or current["price"]),
                "price_observed_at": current["observed_at"].isoformat(),
            })
        equity = cash + value
        peak = self._equity_peak(cur, str(portfolio["portfolio_id"]), _float(portfolio["initial_cash_usdt"]))
        return {
            **self._serialize(portfolio), "cash_usdt": cash, "positions_value_usdt": value,
            "equity_usdt": equity, "realized_pnl_usdt": realized,
            "total_return": equity / _float(portfolio["initial_cash_usdt"]) - 1.0,
            "drawdown": min(0.0, equity / peak - 1.0) if peak else 0.0,
            "positions": positions,
        }

    @staticmethod
    def _portfolio_row(cur, user_key, portfolio_id):
        cur.execute(
            "select * from paper.portfolio where portfolio_id=%s and user_key=%s",
            (portfolio_id, user_key),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError("paper portfolio not found")
        return row

    @staticmethod
    def _decision_row(cur, portfolio_id, decision_id):
        cur.execute(
            "select * from paper.decision where decision_id=%s and portfolio_id=%s",
            (decision_id, portfolio_id),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError("paper decision not found")
        return row

    @staticmethod
    def _replay(cur, portfolio_id: str, initial_cash: float):
        cur.execute(
            """select o.symbol,o.side,f.quantity,f.fill_price_usdt,f.notional_usdt
               from paper.paper_order o join paper.fill f using(order_id)
               where o.portfolio_id=%s and o.status='FILLED' order by f.executed_at,f.fill_id""",
            (portfolio_id,),
        )
        states: dict[str, dict] = {}
        cash, realized = initial_cash, 0.0
        for row in cur.fetchall():
            symbol, side = row["symbol"], row["side"]
            quantity, price, notional = map(_float, (row["quantity"], row["fill_price_usdt"], row["notional_usdt"]))
            state = states.setdefault(symbol, {"quantity": 0.0, "average_entry": None})
            if side == "BUY":
                new_quantity = state["quantity"] + quantity
                state["average_entry"] = (
                    state["quantity"] * (state["average_entry"] or 0.0) + notional
                ) / new_quantity
                state["quantity"] = new_quantity
                cash -= notional
            else:
                realized += quantity * (price - (state["average_entry"] or price))
                state["quantity"] = max(0.0, state["quantity"] - quantity)
                if state["quantity"] <= 1e-12:
                    state["quantity"], state["average_entry"] = 0.0, None
                cash += notional
        return states, cash, realized

    @staticmethod
    def _latest_prices(cur, symbols: tuple[str, ...]) -> dict[str, dict]:
        if not symbols:
            return {}
        cur.execute(
            """select distinct on(symbol) symbol,close_price::float8 as price,close_time
               from dw.fact_candle_minute_live
               where symbol=any(%s) and close_time < now()
               order by symbol,open_time desc""",
            (list(symbols),),
        )
        result = {
            row["symbol"]: {"price": _float(row["price"]), "observed_at": row["close_time"]}
            for row in cur.fetchall()
        }
        missing = set(symbols) - set(result)
        if missing:
            raise ValueError(f"no closed one-minute execution price for {sorted(missing)}")
        return result

    @staticmethod
    def _equity_peak(cur, portfolio_id: str, initial_cash: float) -> float:
        cur.execute(
            "select max(equity_usdt)::float8 as peak from paper.equity_snapshot where portfolio_id=%s",
            (portfolio_id,),
        )
        return max(initial_cash, _float(cur.fetchone()["peak"], initial_cash))

    def _preview(
        self, cur, portfolio, decision, slippage_bps: float,
        max_price_age_seconds: int = 300,
    ) -> OrderPreview:
        if not decision["executable"] or decision["action"] not in ("BUY", "SELL"):
            raise ValueError("decision is advisory-only and cannot create an order")
        now = datetime.now(UTC)
        if decision["valid_until"] <= now:
            raise ValueError("decision expired")
        states, cash, _ = self._replay(cur, str(portfolio["portfolio_id"]), _float(portfolio["initial_cash_usdt"]))
        price = self._latest_prices(cur, (decision["symbol"],))[decision["symbol"]]
        if (now - price["observed_at"]).total_seconds() > max_price_age_seconds:
            raise ValueError("execution price is stale")
        position = states.get(decision["symbol"], {"quantity": 0.0})
        side = decision["action"]
        fill_price = price["price"] * (1 + slippage_bps / 10000.0 if side == "BUY" else 1 - slippage_bps / 10000.0)
        requested = _float(decision["order_notional_usdt"])
        if side == "BUY":
            notional = min(requested, cash)
            quantity = notional / fill_price
            cash_after = cash - notional
            quantity_after = position["quantity"] + quantity
        else:
            quantity = min(position["quantity"], requested / fill_price)
            notional = quantity * fill_price
            cash_after = cash + notional
            quantity_after = max(0.0, position["quantity"] - quantity)
        if notional <= 0 or quantity <= 0 or cash_after < -1e-8 or quantity_after < -1e-12:
            raise ValueError("order violates long-only cash/position constraints")
        return OrderPreview(
            decision_id=str(decision["decision_id"]), portfolio_id=str(portfolio["portfolio_id"]),
            symbol=decision["symbol"], side=side, quantity=quantity,
            market_price_usdt=price["price"], fill_price_usdt=fill_price,
            notional_usdt=notional, slippage_bps=slippage_bps,
            source_candle_time=price["observed_at"], cash_after_usdt=max(0.0, cash_after),
            position_quantity_after=max(0.0, quantity_after),
        )

    @classmethod
    def _serialize(cls, value):
        if isinstance(value, dict):
            return {key: cls._serialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._serialize(item) for item in value]
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value


def summarize_trade_outcomes(rows: list[dict], portfolio: dict) -> dict:
    """Pure aggregation used by the API and unit tests.

    `estimated_next_day_effect_usdt` measures whether the accepted action helped
    over its forecast horizon. It is diagnostic attribution, not realized P&L.
    """
    enriched, useful, harmful, pending = [], 0, 0, 0
    gross_profit, gross_loss = 0.0, 0.0
    by_side = {side: {"evaluated": 0, "useful": 0, "harmful_or_flat": 0} for side in ("BUY", "SELL")}
    for source in rows:
        row = dict(source)
        actual = row.get("actual_target_close_usdt")
        fill = _float(row.get("fill_price_usdt"))
        quantity = _float(row.get("quantity"))
        if actual is None:
            pending += 1
            row.update(outcome="PENDING", estimated_next_day_effect_usdt=None)
        else:
            actual = float(actual)
            effect = quantity * (actual - fill)
            if row["side"] == "SELL":
                # A sell's benefit is avoided loss; this is not short-sale P&L.
                effect = -effect
            is_useful = effect > 0
            useful += int(is_useful)
            harmful += int(not is_useful)
            gross_profit += max(effect, 0.0)
            gross_loss += max(-effect, 0.0)
            side = by_side[row["side"]]
            side["evaluated"] += 1
            side["useful" if is_useful else "harmful_or_flat"] += 1
            row.update(
                outcome="USEFUL" if is_useful else "HARMFUL_OR_FLAT",
                estimated_next_day_effect_usdt=effect,
                actual_target_return=actual / _float(row.get("reference_close_usdt"), fill) - 1.0,
            )
        enriched.append(row)
    evaluated = useful + harmful
    for values in by_side.values():
        values["useful_rate"] = values["useful"] / values["evaluated"] if values["evaluated"] else None
    return {
        "accepted_order_count": len(rows), "evaluated_order_count": evaluated,
        "pending_order_count": pending, "useful_count": useful,
        "harmful_or_flat_count": harmful,
        "useful_rate": useful / evaluated if evaluated else None,
        "gross_useful_effect_usdt": gross_profit,
        "gross_harmful_effect_usdt": gross_loss,
        "net_estimated_next_day_effect_usdt": gross_profit - gross_loss,
        "portfolio_profit_loss_usdt": _float(portfolio.get("equity_usdt")) - _float(portfolio.get("initial_cash_usdt")),
        "portfolio_realized_pnl_usdt": _float(portfolio.get("realized_pnl_usdt")),
        "by_side": by_side, "orders": enriched,
        "effect_definition": "BUY: quantity*(target_close-fill); SELL: quantity*(fill-target_close). Diagnostic only.",
    }

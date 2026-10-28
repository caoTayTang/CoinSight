"""Write portable JSON/CSV artifacts from a policy backtest result."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .backtest import BacktestObservation


class PolicyBacktestReport:
    def write(
        self,
        result: dict,
        output_directory: str | Path,
        observations: Iterable[BacktestObservation] | None = None,
    ) -> dict[str, str]:
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)
        summary_path = directory / "policy_backtest.json"
        curve_path = directory / "policy_equity_curve.csv"
        trades_path = directory / "policy_trades.csv"
        observations_path = directory / "policy_observations.jsonl"
        chart_path = directory / "policy_equity_curve.png"
        direction_path = directory / "policy_direction_confusion.csv"
        hold_reasons_path = directory / "policy_hold_reasons.csv"
        action_utility_path = directory / "policy_action_utility.csv"
        summary = {key: value for key, value in result.items() if key not in ("equity_curve", "trades")}
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        self._csv(curve_path, result.get("equity_curve", []))
        self._csv(trades_path, result.get("trades", []))
        direction = result.get("forecast_direction_diagnostics", {})
        counts = direction.get("counts", {})
        rates = direction.get("rates_over_evaluated", {})
        self._csv(direction_path, [
            {"case": name, "count": count, "rate": rates.get(name)}
            for name, count in counts.items()
        ])
        self._csv(hold_reasons_path, [
            {"reason": reason, "count": count}
            for reason, count in result.get("hold_reason_counts", {}).items()
        ])
        self._csv(action_utility_path, [
            {"side": side, **values}
            for side, values in result.get("policy_action_utility", {}).items()
        ])
        artifacts = {
            "summary": str(summary_path),
            "equity_curve": str(curve_path),
            "trades": str(trades_path),
            "direction_confusion": str(direction_path),
            "hold_reasons": str(hold_reasons_path),
            "action_utility": str(action_utility_path),
        }
        if observations is not None:
            with observations_path.open("w", encoding="utf-8") as handle:
                for row in observations:
                    handle.write(json.dumps({
                        "observed_at": row.observed_at.isoformat(),
                        "symbol": row.symbol,
                        "market_price_usdt": row.market_price_usdt,
                        "actual_target_close_usdt": row.actual_target_close_usdt,
                        "support": row.support,
                    }, sort_keys=True) + "\n")
            artifacts["observations"] = str(observations_path)
        self._plot(result.get("equity_curve", []), chart_path)
        artifacts["chart"] = str(chart_path)
        return artifacts

    @staticmethod
    def _csv(path: Path, rows: list[dict]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            if not rows:
                return
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _plot(rows: list[dict], path: Path) -> None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not rows:
            raise ValueError("cannot plot an empty equity curve")
        dates = [row["observed_at"] for row in rows]
        policy = [row["equity_usdt"] for row in rows]
        benchmark = [row["buy_hold_equity_usdt"] for row in rows]
        figure, axis = plt.subplots(figsize=(12, 6))
        axis.plot(dates, policy, label="Policy equity", linewidth=1.8)
        axis.plot(dates, benchmark, label="Buy & hold", linewidth=1.3, alpha=0.8)
        axis.set_title("Policy backtest: equity vs buy-and-hold")
        axis.set_ylabel("Equity (USDT)")
        axis.set_xlabel("UTC decision cutoff")
        axis.grid(alpha=0.25)
        axis.legend()
        axis.xaxis.set_major_locator(plt.MaxNLocator(8))
        figure.autofmt_xdate()
        figure.tight_layout()
        figure.savefig(path, dpi=150)
        plt.close(figure)

"""Load and checksum immutable JSON policy configuration."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any


class PolicyStore:
    REQUIRED = {
        "policy_id", "version", "mode", "min_performance_samples",
        "trade_threshold", "max_asset_fraction", "max_order_fraction",
        "max_annualized_volatility", "max_market_drawdown_fraction",
        "max_portfolio_drawdown_fraction", "rebalance_tolerance",
        "slippage_bps", "max_price_age_seconds",
    }

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or Path(__file__).with_name("policies"))

    @staticmethod
    def _canonical(config: dict[str, Any]) -> bytes:
        return json.dumps(
            config, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")

    def validate(self, value: dict[str, Any]) -> dict[str, Any]:
        """Return a normalized, checksummed policy without mutating the caller."""
        config = dict(value)
        config.pop("sha256", None)
        missing = self.REQUIRED - set(config)
        if missing:
            raise ValueError(f"policy config missing fields: {sorted(missing)}")
        if config["policy_id"] != "daily-quantile":
            raise ValueError("only daily-quantile policy_id is supported")
        if config["mode"] != "long_only_spot":
            raise ValueError("only long_only_spot is supported")
        if not str(config["version"]).strip():
            raise ValueError("policy version must not be empty")
        config["min_performance_samples"] = int(config["min_performance_samples"])
        config["max_price_age_seconds"] = int(config["max_price_age_seconds"])
        for name in (
            "trade_threshold", "max_asset_fraction", "max_order_fraction",
            "max_annualized_volatility", "max_market_drawdown_fraction",
            "max_portfolio_drawdown_fraction", "rebalance_tolerance", "slippage_bps",
        ):
            config[name] = float(config[name])
        for name in (
            "trade_threshold", "max_asset_fraction", "max_order_fraction",
            "max_market_drawdown_fraction", "max_portfolio_drawdown_fraction",
            "rebalance_tolerance",
        ):
            if not 0 <= config[name] <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if config["max_annualized_volatility"] <= 0:
            raise ValueError("max_annualized_volatility must be positive")
        if not 0 <= config["slippage_bps"] <= 100:
            raise ValueError("slippage_bps must be in [0, 100]")
        if not 7 <= config["min_performance_samples"] <= 365:
            raise ValueError("min_performance_samples must be in [7, 365]")
        if not 30 <= config["max_price_age_seconds"] <= 3600:
            raise ValueError("max_price_age_seconds must be in [30, 3600]")
        config["notes"] = str(config.get("notes", ""))[:1000]
        config["sha256"] = hashlib.sha256(self._canonical(config)).hexdigest()
        return config

    def normalize_user_config(self, value: dict[str, Any]) -> dict[str, Any]:
        """Freeze editable values into a stable user-policy version/checksum."""
        base = self.load("daily_quantile_v1")
        editable = {
            key: value[key]
            for key in (
                "min_performance_samples", "trade_threshold", "max_asset_fraction",
                "max_order_fraction", "max_annualized_volatility",
                "max_market_drawdown_fraction", "max_portfolio_drawdown_fraction",
                "rebalance_tolerance", "slippage_bps", "max_price_age_seconds", "notes",
            )
            if key in value
        }
        candidate = {**base, **editable}
        candidate.pop("sha256", None)
        digest = hashlib.sha256(self._canonical(editable)).hexdigest()[:12]
        candidate.update(
            policy_id="daily-quantile", version=f"v1-user-{digest}",
            deployment_tier="paper-only", mode="long_only_spot",
        )
        return self.validate(candidate)

    @lru_cache(maxsize=8)
    def load(self, version: str = "daily_quantile_v1") -> dict[str, Any]:
        if not version.replace("_", "").isalnum():
            raise ValueError("invalid policy version")
        path = self.root / f"{version}.json"
        raw = path.read_bytes()
        config = self.validate(json.loads(raw))
        # Preserve the checked-in artifact checksum for existing manifests.
        config["sha256"] = hashlib.sha256(raw).hexdigest()
        return config

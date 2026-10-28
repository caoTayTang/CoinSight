import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import yaml


load_dotenv()


def load_settings(path: Path | None = None) -> dict:
    """Load checked-in pipeline choices independently of the working directory."""
    path = path or Path(__file__).with_name("settings.yaml")
    with path.open(encoding="utf-8") as source:
        settings = yaml.safe_load(source)
    if not isinstance(settings, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    batch = settings.get("batch", {})
    if not isinstance(batch, dict) or not batch.get("symbols"):
        raise ValueError("batch.symbols must contain at least one symbol")
    if set(batch.get("intervals", [])) != {"1d", "1h"}:
        raise ValueError("batch.intervals must contain exactly 1d and 1h for the current warehouse")
    if settings.get("live", {}).get("interval") != "1m":
        raise ValueError("live.interval must be 1m for the current stream contract")
    if not 0 <= batch.get("reject_threshold", -1) <= 1:
        raise ValueError("batch.reject_threshold must be between 0 and 1")
    forecasting = settings.get("forecasting", {})
    if not isinstance(forecasting, dict) or not forecasting.get("symbols"):
        raise ValueError("forecasting.symbols must contain at least one symbol")
    frequency = str(forecasting.get("frequency", "1h"))
    if frequency not in {"1h", "1d"}:
        raise ValueError("forecasting.frequency must be either 1h or 1d")
    lookback = forecasting.get("lookback_periods", forecasting.get("lookback_hours", 0))
    horizon = forecasting.get("horizon_periods", forecasting.get("horizon_hours", 0))
    if not isinstance(lookback, int) or lookback <= 1:
        raise ValueError("forecasting.lookback_periods must be greater than one")
    if not isinstance(horizon, int) or horizon <= 0:
        raise ValueError("forecasting.horizon_periods must be positive")
    feature_version = str(forecasting.get("feature_version", ""))
    expected_prefix = "hourly-" if frequency == "1h" else "daily-"
    if not feature_version.startswith(expected_prefix):
        raise ValueError(
            "forecasting.feature_version does not match forecasting.frequency"
        )
    context_symbols = forecasting.get("context_symbols", forecasting.get("symbols", []))
    if not context_symbols:
        raise ValueError("forecasting.context_symbols must contain at least one symbol")
    missing_context = set(forecasting["symbols"]) - set(context_symbols)
    if missing_context:
        raise ValueError(
            "forecasting.context_symbols must include forecasting.symbols: "
            f"{sorted(missing_context)}"
        )
    anomaly = settings.get("market_anomaly", {})
    if anomaly:
        if set(anomaly.get("symbols", [])) != {"BTC", "ETH"}:
            raise ValueError("market_anomaly.symbols must contain BTC and ETH")
        if set(anomaly.get("frequencies", [])) != {"1h", "1d"}:
            raise ValueError("market_anomaly.frequencies must contain 1h and 1d")
        threshold_quantile = anomaly.get("threshold_quantile")
        if not isinstance(threshold_quantile, (int, float)) or not 0.95 <= threshold_quantile < 1:
            raise ValueError("market_anomaly.threshold_quantile must be in [0.95, 1)")
        try:
            boundaries = [
                datetime.fromisoformat(str(anomaly.get(name)).replace("Z", "+00:00"))
                for name in ("train_start", "calibration_start", "test_start")
            ]
        except (TypeError, ValueError):
            raise ValueError(
                "market_anomaly boundaries must be ISO-8601 timestamps"
            ) from None
        if not boundaries[0] < boundaries[1] < boundaries[2]:
            raise ValueError(
                "market_anomaly boundaries must satisfy train_start < calibration_start < test_start"
            )
    return settings


SETTINGS = load_settings()
BATCH = SETTINGS["batch"]
LIVE = SETTINGS["live"]
STREAM = SETTINGS["stream"]
DSS = SETTINGS["dss"]
FORECASTING = SETTINGS["forecasting"]
MARKET_ANOMALY = SETTINGS.get("market_anomaly", {})

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw"
)

BINANCE_DATA_URL = os.getenv("BINANCE_DATA_URL", "https://data.binance.vision")
BATCH_SYMBOLS = ",".join(BATCH["symbols"])
BATCH_INTERVALS = ",".join(BATCH["intervals"])
BATCH_START_MONTH = BATCH["start_month"]
RAW_DIR = os.getenv("RAW_DIR", "../data/raw")
FORECAST_SNAPSHOT_DIR = os.getenv(
    "FORECAST_SNAPSHOT_DIR", "data/forecasting/snapshots"
)
FORECAST_RUN_DIR = os.getenv("FORECAST_RUN_DIR", "data/forecasting/runs")

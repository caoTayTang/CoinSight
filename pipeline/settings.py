import os
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
    return settings


SETTINGS = load_settings()
BATCH = SETTINGS["batch"]
LIVE = SETTINGS["live"]
STREAM = SETTINGS["stream"]
DSS = SETTINGS["dss"]
REPLAY = SETTINGS["replay"]

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw"
)
SAMPLE_CSV = os.getenv("SAMPLE_CSV", "../data/sample.csv")

BINANCE_DATA_URL = os.getenv("BINANCE_DATA_URL", "https://data.binance.vision")
BATCH_SYMBOLS = ",".join(BATCH["symbols"])
BATCH_INTERVALS = ",".join(BATCH["intervals"])
BATCH_START_MONTH = BATCH["start_month"]
RAW_DIR = os.getenv("RAW_DIR", "../data/raw")

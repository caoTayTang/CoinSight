from pathlib import Path

from pipeline.batch_etl import load_prices


def test_load_prices_accepts_sample_csv():
    sample = Path(__file__).parents[1] / "data" / "sample.csv"
    df = load_prices(str(sample))
    assert set(df["symbol"]) == {"BTC", "ETH", "SOL"}
    assert len(df) == 6


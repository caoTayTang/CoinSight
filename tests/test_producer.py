from pathlib import Path

from pipeline.producer import load_events


def test_load_events_normalizes_filters_and_sorts(tmp_path: Path):
    source = tmp_path / "prices.csv"
    source.write_text(
        "Date,Open,High,Low,Close,Volume,ticker,name\n"
        "2025-01-02 00:00:00+00:00,2,3,1,2.5,20,BTC-USD,Bitcoin\n"
        "2025-01-01 00:00:00+00:00,1,2,0.5,1.5,10,BTC-USD,Bitcoin\n"
        "2025-01-01 00:00:00+00:00,3,4,2,3.5,30,ETH-USD,Ethereum\n",
        encoding="utf-8",
    )

    events = load_events(source, {"BTC"})

    assert [event["close_price"] for event in events] == [1.5, 2.5]
    assert all(event["symbol"] == "BTC" for event in events)
    assert events[0]["event_id"].startswith("BTC:2025-01-01")


def test_load_events_rejects_missing_columns(tmp_path: Path):
    source = tmp_path / "prices.csv"
    source.write_text("Date,Close\n2025-01-01,1\n", encoding="utf-8")

    try:
        load_events(source)
    except ValueError as error:
        assert "missing columns" in str(error)
    else:
        raise AssertionError("expected missing columns to fail")

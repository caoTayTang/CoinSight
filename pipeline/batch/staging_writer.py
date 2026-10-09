"""PostgreSQL staging and source-file lineage for Binance archives."""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from pipeline.batch.binance_archive_format import QUOTE_ASSET, kline_url, parse_kline_csv, read_zip_csv
from pipeline.settings import BINANCE_DATA_URL

SOURCE_CODE = "binance"
STAGING_COLUMNS = (
    "batch_id", "source_code", "symbol", "candle_interval", "open_time",
    "open_price", "high_price", "low_price", "close_price", "volume_base",
    "volume_quote", "trade_count", "source_file",
)

def staging_csv(batch_id: int, symbol: str, interval: str, path: Path) -> tuple[io.StringIO, int]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    rows = parse_kline_csv(read_zip_csv(path))
    for row in rows:
        writer.writerow(
            [
                batch_id,
                SOURCE_CODE,
                symbol,
                interval,
                row["open_time"].isoformat(),
                row["open_price"],
                row["high_price"],
                row["low_price"],
                row["close_price"],
                row["volume_base"],
                row["volume_quote"],
                row["trade_count"],
                path.name,
            ]
        )
    buffer.seek(0)
    return buffer, len(rows)


class StagingRepository:
    def __init__(self, database_url: str, archive_url: str = BINANCE_DATA_URL):
        self.database_url = database_url
        self.archive_url = archive_url

    def load(self, files: list[tuple[str, str, Path]], *, replace: bool = True) -> tuple[int, int]:
        import psycopg2

        if not files:
            raise ValueError("no Binance archives to stage")

        connection = psycopg2.connect(self.database_url)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into meta.etl_batch (pipeline, source_code)
                    values ('extract_binance', %s)
                    returning batch_id
                    """,
                    (SOURCE_CODE,),
                )
                batch_id = cursor.fetchone()[0]
            connection.commit()

            try:
                total = 0
                with connection.cursor() as cursor:
                    if replace:
                        cursor.execute(
                            "delete from staging.stg_ohlcv where source_code = %s", (SOURCE_CODE,)
                        )
                    copy_sql = (
                        f"copy staging.stg_ohlcv ({', '.join(STAGING_COLUMNS)}) "
                        "from stdin with (format csv)"
                    )
                    for symbol, interval, path in files:
                        buffer, count = staging_csv(batch_id, symbol, interval, path)
                        cursor.copy_expert(copy_sql, buffer)
                        cursor.execute(
                            """
                            insert into meta.source_file_manifest
                                (extract_batch_id, source_file, symbol, candle_interval,
                                 sha256, rows_extracted, source_url)
                            values (%s, %s, %s, %s, %s, %s, %s)
                            on conflict (extract_batch_id, source_file) do nothing
                            """,
                            (batch_id, path.name, symbol, interval,
                             hashlib.sha256(path.read_bytes()).hexdigest(), count,
                             kline_url(
                                 self.archive_url, symbol, interval,
                                 path.stem.removeprefix(f"{symbol.upper()}{QUOTE_ASSET}-{interval}-"),
                             )),
                        )
                        total += count
                    cursor.execute(
                        """
                        update meta.etl_batch
                        set status = 'success', finished_at = clock_timestamp(), rows_extracted = %s
                        where batch_id = %s
                        """,
                        (total, batch_id),
                    )
                connection.commit()
            except Exception as error:
                connection.rollback()
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        update meta.etl_batch
                        set status = 'failed', finished_at = clock_timestamp(), message = %s
                        where batch_id = %s
                        """,
                        (str(error)[:1000], batch_id),
                    )
                connection.commit()
                raise
        finally:
            connection.close()
        return batch_id, total

    def loaded_checksums(self, filenames: list[str]) -> dict[str, str]:
        import psycopg2

        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select source_file, sha256 from meta.loaded_archive where source_file = any(%s)",
                (filenames,),
            )
            return dict(cursor.fetchall())

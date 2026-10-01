import os

from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw"
)
SAMPLE_CSV = os.getenv("SAMPLE_CSV", "../data/sample.csv")

BINANCE_DATA_URL = os.getenv("BINANCE_DATA_URL", "https://data.binance.vision")
BATCH_SYMBOLS = os.getenv(
    "BATCH_SYMBOLS",
    "BTC,ETH,BNB,SOL,XRP,ADA,DOGE,TRX,AVAX,LINK,"
    "DOT,LTC,BCH,UNI,ATOM,XLM,ETC,FIL,NEAR,SHIB",
)
BATCH_INTERVALS = os.getenv("BATCH_INTERVALS", "1d,1h")
BATCH_START_MONTH = os.getenv("BATCH_START_MONTH", "2020-01")
RAW_DIR = os.getenv("RAW_DIR", "../data/raw")

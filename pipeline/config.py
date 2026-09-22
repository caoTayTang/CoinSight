import os

from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw"
)
SAMPLE_CSV = os.getenv("SAMPLE_CSV", "../data/sample.csv")

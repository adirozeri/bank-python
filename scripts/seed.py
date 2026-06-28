import random
import sys
from pathlib import Path

from dotenv import load_dotenv

# Put the repo root on sys.path so `python scripts/seed.py` can import `app`, and load .env
# before importing app.database (it reads DATABASE_URL / ANALYTICS_URL at import time).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from app.database import Base, SessionLocal, engine
from app.models import Transaction
from scripts.sync_to_snowflake import sync

Base.metadata.create_all(bind=engine)

ACCOUNTS = ["A1", "A2", "A3"]
CATEGORIES = ["groceries", "salary", "rent", "utilities", "dining"]
TYPES = [ "credit", "transfer"]
STATUSES = ["pending", "completed", "failed"]
CURRENCY = ["USD", "NIS", "GBP"]

db = SessionLocal()
for _ in range(50):
    db.add(
        Transaction(
            account_id=random.choice(ACCOUNTS),
            amount=round(random.uniform(5, 5000), 2),
            currency=random.choice(CURRENCY),
            type=random.choice(TYPES),
            status=random.choice(STATUSES),
            category=random.choice(CATEGORIES),
            counterparty="Sample Co",
        )
    )
db.commit()
db.close()
print("Seeded 50 transactions.")

# Mirror the freshly-seeded rows into Snowflake so the /ask read tools see them.
# No-op if ANALYTICS_URL is unset (analytics then uses the primary DB).
sync()

import random

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.database (it reads DATABASE_URL at import)

from app.database import Base, SessionLocal, engine
from app.models import Transaction

Base.metadata.create_all(bind=engine)

ACCOUNTS = ["ACC-0001", "ACC-0002", "ACC-0003"]
CATEGORIES = ["groceries", "salary", "rent", "utilities", "dining"]
TYPES = ["debit", "credit", "transfer"]
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

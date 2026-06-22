"""Sync transactions from the primary DB (Postgres) into Snowflake for analytics.

Postgres is the source of truth (all writes). Snowflake is a read-only replica that the
/ask read tools query. This script copies *new* rows (incremental by `created_at`) from the
primary engine into the analytics engine, so the two stay eventually consistent.

Run it on a schedule (a host `cron` entry on the EC2 box, see docs/aws_ec2.md), e.g.:
    */15 * * * * cd /path/to/bank-python && docker compose run --rm app \
        python scripts/sync_to_snowflake.py

No-op (and safe to re-run) when ANALYTICS_URL is unset: the analytics engine then *is* the
primary engine, so there's nothing to sync and the script exits early.
"""

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.database (it reads the URLs at import time)

from sqlalchemy import func, select

from app.database import (
    ANALYTICS_URL,
    AnalyticsSession,
    Base,
    SessionLocal,
    analytics_engine,
)
from app.models import Transaction

# How many rows to copy per round-trip. Keeps memory bounded if a lot has accumulated.
BATCH_SIZE = 500


def _columns(txn: Transaction) -> dict:
    """Plain dict of a Transaction's column values (for re-inserting into Snowflake)."""
    return {col.name: getattr(txn, col.name) for col in Transaction.__table__.columns}


def sync() -> int:
    """Copy rows created after the latest already in Snowflake. Returns rows synced."""
    if not ANALYTICS_URL:
        print("ANALYTICS_URL not set — analytics uses the primary DB; nothing to sync.")
        return 0

    # Ensure the destination table exists (idempotent — same model, Snowflake dialect).
    Base.metadata.create_all(bind=analytics_engine)

    # Watermark: the newest created_at already in Snowflake. Only copy rows after it.
    with AnalyticsSession() as dest:
        watermark = dest.scalar(select(func.max(Transaction.created_at)))

    total = 0
    with SessionLocal() as src:
        stmt = select(Transaction).order_by(Transaction.created_at)
        if watermark is not None:
            stmt = stmt.where(Transaction.created_at > watermark)

        new_rows = src.scalars(stmt).all()

    # Insert into Snowflake in batches.
    for start in range(0, len(new_rows), BATCH_SIZE):
        batch = new_rows[start : start + BATCH_SIZE]
        with AnalyticsSession() as dest:
            dest.add_all([Transaction(**_columns(t)) for t in batch])
            dest.commit()
        total += len(batch)

    since = watermark.isoformat() if watermark else "the beginning"
    print(f"Synced {total} transaction(s) created after {since}.")
    return total


if __name__ == "__main__":
    sync()

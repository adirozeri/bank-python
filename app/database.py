import os
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bank.db")

# SQLite needs check_same_thread=False to be used across threads (FastAPI);
# Postgres and other backends neither need nor accept that arg.
is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}

# pool_pre_ping validates connections before use, avoiding "server closed the
# connection unexpectedly" errors when Postgres drops idle conns (common in k8s).
engine = create_engine(url=DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)

# --- Analytics engine (Snowflake reads) ---
# The /ask read tools can run against a separate analytics warehouse (Snowflake) while all
# writes stay on the primary engine (Postgres = source of truth). If ANALYTICS_URL is unset
# (local dev / Phase 1), this transparently falls back to the primary engine, so the code
# runs identically everywhere and only "splits" once a Snowflake URL is provided.
ANALYTICS_URL = os.getenv("ANALYTICS_URL")
if ANALYTICS_URL:
    # Snowflake auth tokens expire on long-running processes. client_session_keep_alive sends a
    # heartbeat so the session/token keeps renewing instead of expiring while idle, and
    # pool_recycle drops any connection older than an hour so a stale (post-token) one is never
    # reused — otherwise reads fail with "390114 Authentication token has expired".
    _analytics_connect_args = (
        {"client_session_keep_alive": True} if ANALYTICS_URL.startswith("snowflake") else {}
    )
    analytics_engine = create_engine(
        url=ANALYTICS_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args=_analytics_connect_args,
    )
    AnalyticsSession = sessionmaker(bind=analytics_engine, autoflush=False)
else:
    analytics_engine = engine
    AnalyticsSession = SessionLocal


class Base(DeclarativeBase):
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

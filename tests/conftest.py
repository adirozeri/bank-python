"""Shared fixtures for the test suite.

The /ask agent reads/writes through SQLAlchemy sessions and, for real answers, calls the
LLM providers (Gemini/Groq). Unit tests must touch neither a real database nor the network,
so we spin up a throwaway in-memory SQLite database and repoint the DB-access module's
session factories at it.

Note: app/llm/data_access.py does `from ..database import AnalyticsSession, SessionLocal`,
which binds those names inside the data_access module. Patching app.database is therefore
not enough — we patch the copies that live on app.llm.data_access.
"""

import os
import sys
from datetime import datetime

# Provider API keys aren't needed to import the package (models are built lazily and mocked
# in tests), but set placeholders so any incidental construction can't fail.
os.environ.setdefault("GOOGLE_API_KEY", "test-not-used")
os.environ.setdefault("GROQ_API_KEY", "test-not-used")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-used")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.llm import data_access as data_access_module
from app.database import Base
from app.models import Transaction


@pytest.fixture(autouse=True)
def mock_mcp(monkeypatch):
    """Serve config/prompts to the app's MCP client WITHOUT a running server or network.

    The LangGraph service now fetches its routing config and prompts from the MCP server. To
    keep unit tests offline, we patch app.llm.mcp_client's fetch_* functions to read the same
    files the server would serve (via mcp_server.files) — so the canned data can never drift
    from the real prompts. lru_caches that wrap these are cleared around each test.
    """
    from mcp_server import files as mcp_files
    from app.llm import config, factory, mcp_client

    monkeypatch.setattr(mcp_client, "fetch_config", lambda: mcp_files.read_routing())

    def _fetch_prompt(role):
        return mcp_files.read_prompt(mcp_client._prompt_name_for(role))

    def _fetch_response_prompt(persona_key=None):
        return f"{mcp_files.read_prompt('response')}\n\n{mcp_files.resolve_persona(persona_key)}"

    monkeypatch.setattr(mcp_client, "fetch_prompt", _fetch_prompt)
    monkeypatch.setattr(mcp_client, "fetch_response_prompt", _fetch_response_prompt)

    for cached in (config.load_llm_config, factory.get_llm):
        cached.cache_clear()
    yield
    for cached in (config.load_llm_config, factory.get_llm):
        cached.cache_clear()


@pytest.fixture
def session_factory(monkeypatch):
    """A sessionmaker bound to a fresh in-memory SQLite DB, wired into app.llm.data_access.

    StaticPool keeps a single underlying connection so every session in a test sees
    the same in-memory database (a plain "sqlite://" gives each connection its own).
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    # Reads (AnalyticsSession) and writes (SessionLocal) both go to the test DB.
    monkeypatch.setattr(data_access_module, "SessionLocal", TestSession)
    monkeypatch.setattr(data_access_module, "AnalyticsSession", TestSession)
    return TestSession


@pytest.fixture
def seeded(session_factory):
    """session_factory pre-populated with a small, predictable ledger."""
    with session_factory() as s:
        s.add_all(
            [
                Transaction(account_id="ACC-0001", amount=100.0, type="credit", status="completed"),
                Transaction(account_id="ACC-0001", amount=30.0, type="debit", status="completed"),
                # Pending row: must be ignored by the balance calc.
                Transaction(account_id="ACC-0001", amount=999.0, type="credit", status="pending"),
                Transaction(account_id="ACC-0002", amount=50.0, type="credit", status="completed"),
            ]
        )
        s.commit()
    return session_factory


def pytest_configure(config):
    if not config.pluginmanager.hasplugin("html"):
        return

    files = [arg for arg in config.invocation_params.args if arg.endswith(".py")]
    if not files:
        return

    test_file = files[0]
    folder = os.path.dirname(os.path.abspath(test_file))
    name = os.path.splitext(os.path.basename(test_file))[0]

    reports_dir = os.path.join(folder, "reports")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config.option.htmlpath = os.path.join(reports_dir, name + "_" + timestamp + ".html")


@pytest.fixture(scope="session", autouse=True)
def _allure_environment():
    """Populate the Allure report's Environment widget.

    allure-pytest reads <alluredir>/environment.properties at report-generation time.
    Written only when --alluredir was passed (the dir exists by collection time because
    --clean-alluredir creates it); otherwise this is a no-op.
    """
    alluredir = "allure-results"
    if not os.path.isdir(alluredir):
        return
    props = {
        "Python": sys.version.split()[0],
        "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite:///./bank.db"),
        "ANALYTICS_URL": os.getenv("ANALYTICS_URL", "(falls back to primary)"),
        "LLM_providers": "Gemini (user_intent, judge) + Groq (risk_analysis)",
    }
    with open(os.path.join(alluredir, "environment.properties"), "w") as fh:
        fh.writelines(f"{k}={v}\n" for k, v in props.items())
"""Database access for the LLM workflow.

All SQLAlchemy reads/writes used by the agent live here (moved out of the old monolithic
llm.py) so the graph nodes stay free of ORM details. Reads go to the analytics engine
(Snowflake when configured, else the primary); the transfer write goes to the primary.
"""

import json

from langsmith import traceable
from sqlalchemy import case, func, select

from ..database import AnalyticsSession, SessionLocal
from ..models import Transaction


@traceable(run_type="tool")
def query_transactions(account_id: str | None) -> tuple[str, list[dict]]:
    """Return (sql, rows) for the most recent transactions, optionally filtered by account."""
    stmt = select(Transaction)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    stmt = stmt.order_by(Transaction.created_at.desc()).limit(20)
    with AnalyticsSession() as session:
        txns = session.scalars(stmt).all()
        rows = [
            {col.name: getattr(t, col.name) for col in Transaction.__table__.columns}
            for t in txns
        ]
    return str(stmt), rows


@traceable(run_type="tool")
def query_balance(account_id: str | None) -> tuple[str, list[dict]]:
    """Return (sql, rows) of completed credits minus debits/transfers, per account+currency."""
    balance = func.sum(
        case((Transaction.type == "credit", Transaction.amount), else_=-Transaction.amount)
    ).label("balance")
    stmt = (
        select(Transaction.account_id, Transaction.currency, balance)
        .where(Transaction.status == "completed")
    )
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    stmt = stmt.group_by(Transaction.account_id, Transaction.currency).order_by(
        Transaction.account_id
    )
    with AnalyticsSession() as session:
        rows = [dict(r) for r in session.execute(stmt).mappings().all()]
    return str(stmt), rows


def account_exists(session, account_id: str) -> bool:
    """An account "exists" if it appears anywhere in the transactions ledger."""
    return session.scalar(
        select(Transaction.id).where(Transaction.account_id == account_id).limit(1)
    ) is not None


@traceable(run_type="tool")
def execute_transfer(
    from_account: str, to_account: str, amount: float, currency: str = "USD"
) -> str:
    """Write a confirmed transfer as a double entry (debit sender, credit receiver).

    Returns a human-readable result string. Does NOT confirm or assess risk — callers
    (the transfer node) handle confirmation and the risk/judge gate first.
    """
    with SessionLocal() as session:
        missing = [a for a in (from_account, to_account) if not account_exists(session, account_id=a)]
        if missing:
            return f"Account(s) not found: {', '.join(missing)}. No transfer created."

        # Double-entry: debit the sender (a 'transfer' out), credit the receiver.
        debit = Transaction(
            account_id=from_account, 
            amount=amount, 
            currency=currency, 
            type="transfer",
            status="completed", 
            counterparty=to_account,
            description=f"Transfer to {to_account}",
        )
        credit = Transaction(
            account_id=to_account, 
            amount=amount, 
            currency=currency, 
            type="credit",
            status="completed", 
            counterparty=from_account,
            description=f"Transfer from {from_account}",
        )
        session.add_all([debit, credit])
        session.commit()
        return (
            f"Transfer completed: {amount} {currency} from {from_account} to "
            f"{to_account} (transaction id {debit.id})."
        )


def transactions_json(account_id: str | None) -> str:
    """Convenience for tools: recent transactions as a JSON string."""
    _, rows = query_transactions(account_id=account_id)
    return json.dumps(rows, default=str)


def balance_json(account_id: str | None) -> str:
    """Convenience for tools: balance(s) as a JSON string."""
    _, rows = query_balance(account_id=account_id)
    return json.dumps(rows, default=str)

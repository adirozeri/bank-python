"""Database access for the LLM workflow.

All SQLAlchemy reads/writes used by the agent live here (moved out of the old monolithic
llm.py) so the graph nodes stay free of ORM details. Reads go to the analytics engine
(Snowflake when configured, else the primary); the transfer write goes to the primary.
"""

import json
from collections import Counter

from langsmith import traceable
from sqlalchemy import case, func, select

from ..database import AnalyticsSession, SessionLocal
from ..models import Transaction

# Transaction types that move money OUT of the sender's account.
_OUTFLOW_TYPES = ("debit", "transfer")


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


@traceable(run_type="tool")
def risk_features(transfer: dict) -> dict:
    """Precompute the deterministic risk signals so the LLM does judgement, not arithmetic.

    Pulls the sender's balances + recent history and reduces them to a small, factual
    summary (overdraft checks, per-currency balances, pending-outflow totals, counts) —
    far fewer tokens than the raw rows, and the math is correct by construction.
    """
    account_id = transfer["from_account"]
    currency = transfer["currency"]
    amount = float(transfer["amount"])

    _, balances = query_balance(account_id=account_id)
    _, history = query_transactions(account_id=account_id)

    by_currency = {b["currency"]: round(b["balance"], 2) for b in balances}
    available = by_currency.get(currency, 0.0)

    pending_outflows = round(
        sum(
            h["amount"]
            for h in history
            if h["currency"] == currency
            and h["status"] == "pending"
            and h["type"] in _OUTFLOW_TYPES
        ),
        2,
    )
    outflows = [h["amount"] for h in history if h["type"] in _OUTFLOW_TYPES]

    return {
        "transfer": {k: transfer[k] for k in ("from_account", "to_account", "amount", "currency")},
        "available_balance": available,
        "balances_by_currency": by_currency,
        "negative_currencies": [c for c, v in by_currency.items() if v < 0],
        "amount_pct_of_balance": round(100 * amount / available, 1) if available > 0 else None,
        "pending_outflows_same_currency": pending_outflows,
        "projected_balance_after_pending": round(available - pending_outflows, 2),
        "would_overdraft_now": amount > available,
        "would_overdraft_after_pending": (available - pending_outflows - amount) < 0,
        "status_counts": dict(Counter(h["status"] for h in history)),
        "largest_recent_outflow": round(max(outflows), 2) if outflows else 0.0,
        "history_size": len(history),
    }


def transactions_json(account_id: str | None) -> str:
    """Convenience for tools: recent transactions as a JSON string."""
    _, rows = query_transactions(account_id=account_id)
    return json.dumps(rows, default=str)


def balance_json(account_id: str | None) -> str:
    """Convenience for tools: balance(s) as a JSON string."""
    _, rows = query_balance(account_id=account_id)
    return json.dumps(rows, default=str)

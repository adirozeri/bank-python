from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import llm
from .database import Base, engine, get_db
from .models import Transaction

Base.metadata.create_all(bind=engine)

app = FastAPI(title="bank-python")

db_dependency = Annotated[Session, Depends(get_db)]

# --- Schemas ---
class TransactionIn(BaseModel):
    account_id: str
    amount: float
    type: str
    currency: str = "USD"
    status: str = "pending"
    counterparty: str | None = None
    category: str | None = None
    description: str | None = None


class AskIn(BaseModel):
    question: str
    # Pass the thread_id returned by a previous /ask to continue that conversation;
    # omit it to start a new one.
    thread_id: str | None = None


# --- Endpoints ---


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/transactions")
def create_transaction(data: TransactionIn, db: db_dependency):
    txn = Transaction(**data.model_dump())
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


@app.get("/transactions")
def list_transactions(
    db: db_dependency,
    account_id: str | None = None,
    type: str | None = None,
    status: str | None = None
):
    stmt = select(Transaction)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if type:
        stmt = stmt.where(Transaction.type == type)
    if status:
        stmt = stmt.where(Transaction.status == status)

    ordered_stmt = stmt.order_by(Transaction.created_at.desc())
    result = db.scalars(ordered_stmt)
    transactions = result.all()
    return transactions


@app.get("/transactions/{txn_id}")
def get_transaction(txn_id: str, db: db_dependency):
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    return txn


@app.post("/ask")
def ask(data: AskIn):
    return llm.ask(data.question, data.thread_id)


# SQLAlchemy 2.0 Cheatsheet

A practical reference for the modern (2.0) ORM style. This is the style your
`bank-python` project uses: `select()`, `scalars()`, `DeclarativeBase`.

---

## The four core pieces

Everything in SQLAlchemy comes back to these. Learn them in this order.

| Piece | What it is | In your project |
|-------|-----------|-----------------|
| Engine | The connection to the database. Holds a connection pool. Created once. | `engine = create_engine(...)` in `database.py` |
| Session | Your workspace for one unit of work. Where you add, query, commit. | `SessionLocal()` inside `get_db` |
| Model | A Python class mapped to a table. Instances are rows. | `class Transaction(Base)` in `models.py` |
| Select | A query description you build, then run. | `select(Transaction)` in `main.py` |

---

## Setup

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

DATABASE_URL = "sqlite:///./bank.db"
# Postgres would be: "postgresql+psycopg://user:pass@host:5432/dbname"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False)

class Base(DeclarativeBase):
    pass
```

The connection string is the only thing that changes between databases.
Same code runs on SQLite, Postgres, MySQL.

---

## Defining a model

```python
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

class Transaction(Base):
    __tablename__ = "transactions"   # this names the table, nothing automatic

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str]
    amount: Mapped[float]
    type: Mapped[str]
    currency: Mapped[str] = mapped_column(default="USD")
    counterparty: Mapped[str | None]          # nullable column
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
```

Key points:
* `__tablename__` is what ties the class to the table. The name is your choice.
* `Mapped[int]` is the 2.0 way to declare a column type.
* `Mapped[str | None]` means the column allows NULL.
* `primary_key=True` marks the column used by `db.get`.

Create the tables (development only, never alters existing tables):

```python
Base.metadata.create_all(bind=engine)
```

---

## Sessions

A session is your handle to the database for a unit of work.

```python
db = SessionLocal()
try:
    # do work
    db.commit()
finally:
    db.close()
```

In FastAPI you usually wrap this in a dependency so it is automatic:

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

`yield` (not `return`) is what lets the cleanup run after the response is sent.

---

## INSERT (create a row)

```python
txn = Transaction(account_id="acc_1", amount=50.0, type="debit")
db.add(txn)
db.commit()
db.refresh(txn)   # reload so txn.id and txn.created_at are populated
```

* `add` stages the object.
* `commit` writes it to the database.
* `refresh` re-reads the row so database generated fields (id, timestamps)
  appear on your Python object.

Insert many at once:

```python
db.add_all([txn1, txn2, txn3])
db.commit()
```

---

## SELECT (read rows)

You build a `select()` object, then execute it. Building does not touch the
database. Only executing does.

```python
from sqlalchemy import select

stmt = select(Transaction)                 # SELECT * FROM transactions
```

### scalars vs execute (the common confusion)

| Call | Each result is | Use when |
|------|---------------|----------|
| `db.scalars(stmt)` | the entity, unwrapped | selecting whole objects: `select(Transaction)` |
| `db.execute(stmt)` | a row tuple | selecting columns: `select(Transaction.id, Transaction.amount)` |

```python
# whole entities -> scalars
txns = db.scalars(select(Transaction)).all()
# txns is [Transaction, Transaction, ...]

# specific columns -> execute
rows = db.execute(
    select(Transaction.account_id, Transaction.amount)
).all()
# rows is [(account_id, amount), ...]
```

### Result methods (what goes after scalars/execute)

| Method | Returns |
|--------|---------|
| `.all()` | a list of everything |
| `.first()` | first item, or `None` |
| `.one()` | exactly one, errors if zero or many |
| `.one_or_none()` | one or `None`, errors if many |

---

## Filtering with WHERE

Each `.where(...)` returns a new query, so reassign.

```python
stmt = select(Transaction).where(Transaction.account_id == "acc_1")

# multiple conditions, all must match (AND)
stmt = (
    select(Transaction)
    .where(Transaction.account_id == "acc_1")
    .where(Transaction.status == "pending")
)
```

Building conditionally (the pattern in your list endpoint):

```python
stmt = select(Transaction)
if account_id:
    stmt = stmt.where(Transaction.account_id == account_id)
if status:
    stmt = stmt.where(Transaction.status == status)
```

Common operators:

```python
Transaction.amount > 100
Transaction.amount >= 100
Transaction.status != "void"
Transaction.account_id.in_(["acc_1", "acc_2"])
Transaction.counterparty.is_(None)          # IS NULL
Transaction.description.like("%coffee%")     # pattern match
```

Combine explicitly with `and_` / `or_`:

```python
from sqlalchemy import and_, or_

stmt = select(Transaction).where(
    or_(Transaction.amount > 1000, Transaction.type == "wire")
)
```

---

## Ordering, limiting

```python
from sqlalchemy import select

stmt = (
    select(Transaction)
    .order_by(Transaction.created_at.desc())   # newest first
    .limit(10)
    .offset(20)                                # skip first 20 (paging)
)
```

`.desc()` for descending, `.asc()` (or nothing) for ascending.

---

## Fetch by primary key

```python
txn = db.get(Transaction, txn_id)   # returns the object or None
if txn is None:
    # not found
    ...
```

`db.get` takes (model class, primary key value). It is the fast direct lookup
for a single row when you know its id. It can return from the session cache
without hitting the database.

---

## UPDATE (change a row)

The simple ORM way: load it, change it, commit.

```python
txn = db.get(Transaction, txn_id)
if txn is not None:
    txn.status = "settled"
    db.commit()
```

Bulk update without loading objects:

```python
from sqlalchemy import update

stmt = (
    update(Transaction)
    .where(Transaction.status == "pending")
    .values(status="settled")
)
db.execute(stmt)
db.commit()
```

---

## DELETE (remove a row)

ORM way:

```python
txn = db.get(Transaction, txn_id)
if txn is not None:
    db.delete(txn)
    db.commit()
```

Bulk delete:

```python
from sqlalchemy import delete

stmt = delete(Transaction).where(Transaction.status == "void")
db.execute(stmt)
db.commit()
```

---

## Counting and aggregates

```python
from sqlalchemy import func, select

# count rows
total = db.scalar(select(func.count()).select_from(Transaction))

# sum a column
spent = db.scalar(
    select(func.sum(Transaction.amount))
    .where(Transaction.account_id == "acc_1")
)
```

`db.scalar(...)` (singular) returns a single value, handy for one number
results like counts and sums.

---

## Relationships (linking tables)

When one table references another (foreign key):

```python
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account"
    )

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    account: Mapped["Account"] = relationship(back_populates="transactions")
```

Then you can navigate in Python:

```python
account = db.get(Account, 1)
for txn in account.transactions:   # SQLAlchemy loads them for you
    print(txn.amount)
```

---

## Transactions and safety

A commit writes everything staged since the last commit. A rollback undoes it.

```python
try:
    db.add(txn)
    db.commit()
except Exception:
    db.rollback()   # undo on failure
    raise
```

The `get_db` dependency pattern already closes the session for you, but you
handle commit and rollback inside the endpoint.

---

## Quick SQL translation table

If you know SQL, the ORM maps directly.

| SQL | SQLAlchemy 2.0 |
|-----|----------------|
| `SELECT * FROM transactions` | `select(Transaction)` |
| `WHERE account_id = 'x'` | `.where(Transaction.account_id == "x")` |
| `ORDER BY created_at DESC` | `.order_by(Transaction.created_at.desc())` |
| `LIMIT 10` | `.limit(10)` |
| `INSERT INTO ...` | `db.add(obj); db.commit()` |
| `UPDATE ... SET ...` | `obj.field = x; db.commit()` |
| `DELETE FROM ...` | `db.delete(obj); db.commit()` |
| `SELECT COUNT(*)` | `select(func.count())` |

---

## Gotchas worth remembering

1. Building a `select()` runs nothing. Only `scalars`, `execute`, or `scalar`
   touch the database.
2. `.where()`, `.order_by()`, `.limit()` return new objects. Reassign or chain.
3. `scalars` for whole entities, `execute` for column tuples.
4. After `commit`, call `refresh` if you need database generated values.
5. `create_all` only creates missing tables. It never alters existing ones.
   For schema changes on a real database, use Alembic (the migration tool).
6. SQLite and Postgres differ slightly. Develop on the one you deploy on.

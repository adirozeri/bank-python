"""Tool schemas exposed to the User Intent model.

The @tool objects exist mainly for their *schema* (so the LLM knows what it can call). The
read tools' bodies return data directly; create_transfer's body is a placeholder — the graph
intercepts that call and routes it through the risk -> judge -> confirm subflow instead of
executing here (see nodes/tools_runner.py and nodes/transfer.py).
"""

from langchain_core.tools import tool

from . import data_access


@tool
def list_transactions(account_id: str | None = None) -> str:
    """List recent transactions.

    Optionally filter to a single account by account_id, e.g. "ACC-0001".
    """
    return data_access.transactions_json(account_id)


@tool
def count_transactions(account_id: str | None = None) -> str:
    """Return the EXACT number of transactions, computed by the database.

    Use this for "how many" / count questions instead of list_transactions — it returns the
    precise count so you never have to tally rows yourself (do not count a row list by hand).
    Optionally filter to a single account by account_id, e.g. "A1".
    """
    return data_access.count_json(account_id)


@tool
def get_balance(account_id: str | None = None) -> str:
    """Get account balance(s): completed credits minus completed debits/transfers,
    grouped by account and currency. Optionally filter to a single account_id.
    """
    return data_access.balance_json(account_id)


@tool
def create_transfer(
    from_account: str, to_account: str, amount: float, currency: str = "USD"
) -> str:
    """Transfer money from one account to another. Use this whenever the user asks to move,
    send, or transfer money. The transfer is risk-reviewed, judged, and confirmed before it
    is created.
    """
    # Never actually executed: the graph captures this call and runs the gated subflow.
    return "Transfer request received; running risk review."


# Bound to the intent model for tool-calling; read tools are dispatched by name in the
# tools_runner node, which returns their rows to the agent (never to the API caller).
TOOLS = [list_transactions, count_transactions, get_balance, create_transfer]
READ_HELPERS = {
    "list_transactions": data_access.query_transactions,
    "count_transactions": data_access.query_count,
    "get_balance": data_access.query_balance,
}

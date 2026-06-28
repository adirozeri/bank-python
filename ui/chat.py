"""Streamlit chat UI for the /ask conversational agent.

A separate process from the API: it only talks HTTP to /ask, so nothing in
`app/` imports it. Run alongside the API:

    python -m mcp_server.server    # MCP server (config/prompts) on :8000
    python run.py                  # API on :5002
    streamlit run ui/chat.py       # this UI on :8501
"""

import os

import requests
import streamlit as st

# The API runs on :5002 (the MCP server owns :8000). Override with API_URL in compose.
API_URL = os.getenv("API_URL", "http://127.0.0.1:5002")

st.set_page_config(page_title="bank-python chat", page_icon="💬")
st.title("💬 bank-python")
st.caption("Ask about transactions or account balances — just keep chatting.")


def post_ask(question: str, thread_id: str | None) -> dict:
    """POST one turn to /ask, returning the JSON body (or a synthetic error answer)."""
    payload = {"question": question}
    if thread_id:
        payload["thread_id"] = thread_id
    try:
        resp = requests.post(f"{API_URL}/ask", json=payload, timeout=120)
    except requests.ConnectionError:
        return {"answer": f"Can't reach the API at {API_URL}. Is it running (`python run.py`)?"}
    if resp.status_code != 200:
        return {"answer": f"API error {resp.status_code}: {resp.text}"}
    return resp.json()


def render_answer(result: dict) -> None:
    """Render one assistant turn (the natural-language answer; the API never returns SQL/rows)."""
    st.markdown(result.get("answer", "_(no answer)_"))


# --- Sidebar: S3 presigned-URL image demo ---
# The UI stays HTTP-only: it asks the API for a presigned URL, then st.image lets the
# browser fetch the image straight from S3 with that signed link.
with st.sidebar:
    st.subheader("S3 image (presigned URL)")
    if st.button("Load image from S3"):
        try:
            r = requests.get(f"{API_URL}/s3/image-url", timeout=30)
            r.raise_for_status()
            st.image(r.json()["url"])
        except Exception as e:
            st.error(f"Couldn't load image: {e}")


# --- State ---
# messages: [{"role": "user", "text": str} | {"role": "assistant", "result": dict}]
if "messages" not in st.session_state:
    st.session_state.messages = []

# thread_id: ties every turn to one server-side conversation (carries memory).
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None


# --- Replay the conversation so far ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if "text" in msg:
            st.markdown(msg["text"])
        else:
            render_answer(msg["result"])


# --- New turn ---
if question := st.chat_input("Ask a question…"):
    # Render the user's message immediately, BEFORE the (blocking) API call, so it appears
    # right away instead of only after the server responds.
    st.session_state.messages.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Show an animated "thinking" indicator while the server generates the answer.
    with st.chat_message("assistant"):
        with st.spinner("Generating response…"):
            result = post_ask(question, st.session_state.thread_id)
        render_answer(result)

    # Remember the thread so the next turn continues the same conversation.
    if result.get("thread_id"):
        st.session_state.thread_id = result["thread_id"]
    st.session_state.messages.append({"role": "assistant", "result": result})

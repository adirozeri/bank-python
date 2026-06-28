"""Standalone MCP server microservice for the bank-python LLM workflow.

Owns the LLM **configuration** (model routing/params) and the **prompt** files, and serves
them over MCP (Streamable HTTP). The LangGraph microservice connects as an MCP *client* and
fetches everything from here — it keeps no local copy. This package has no dependency on
``app/`` and is deployed as its own process / Docker image.
"""

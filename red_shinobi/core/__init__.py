"""
RED SHINOBI Core Engine Package

Contains the AI brain, MCP client, and configuration modules.
"""

from red_shinobi.core.config import API_KEYS, PROVIDERS, get_key
from red_shinobi.core.brain import (
    MODEL_REGISTRY,
    DEFAULT_MODEL,
    chat_worker,
    run_agent_conversation,
    human_interrupt,
    get_all_model_names,
    normalize_model_name,
)
from red_shinobi.core.mcp_client import MCPManager, MCPError, MCPConnectionError, MCPProtocolError, MCPTimeoutError

__all__ = [
    "API_KEYS",
    "PROVIDERS",
    "get_key",
    "MODEL_REGISTRY",
    "DEFAULT_MODEL",
    "chat_worker",
    "run_agent_conversation",
    "human_interrupt",
    "get_all_model_names",
    "normalize_model_name",
    "MCPManager",
    "MCPError",
    "MCPConnectionError",
    "MCPProtocolError",
    "MCPTimeoutError",
]

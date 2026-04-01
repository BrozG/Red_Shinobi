"""
RED SHINOBI Commands Package

Contains all CLI command modules. Each module exports an `execute` function
that can be called by the main command router.
"""

from red_shinobi.commands.auth_cmds import execute as auth_execute
from red_shinobi.commands.mcp_cmds import execute as mcp_execute
from red_shinobi.commands.model_cmds import execute as model_execute, system_execute
from red_shinobi.commands.file_cmds import execute as file_execute, save_execute

__all__ = [
    "auth_execute",
    "mcp_execute",
    "model_execute",
    "system_execute",
    "file_execute",
    "save_execute",
]

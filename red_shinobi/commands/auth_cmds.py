"""
RED SHINOBI Authentication Commands Module

Handles the /key command for API key configuration and verification.
"""

import os
from typing import Any, Optional

from dotenv import set_key, load_dotenv
from openai import OpenAI, AuthenticationError
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.styles import Style

from red_shinobi.core import config
from red_shinobi.core.mcp_client import MCPManager

console = Console()
THEME_COLOR = "red"
ACCENT_COLOR = "red"


def check_api_keys() -> None:
    """
    Check which API keys are loaded from os.getenv without crashing.
    Displays status for NVIDIA, OPENAI, and ANTHROPIC providers.
    """
    console.print(f"\n[{THEME_COLOR}]API Key Status:[/{THEME_COLOR}]")
    providers = ["NVIDIA", "OPENAI", "ANTHROPIC"]
    status_symbols = []
    for provider in providers:
        key = os.getenv(f"{provider}_API_KEY")
        if key:
            status_symbols.append(f"[green]{provider} [/green][dim]|[/dim]")
        else:
            status_symbols.append(f"[dim]{provider}[/dim] [dim]|[/dim]")
    console.print(" ".join(status_symbols).rstrip(" [dim]|[/dim]"))
    console.print()


def verify_api_key(provider: str, key: str) -> tuple:
    """
    Verify an API key by making a real request to the provider's servers.
    
    Args:
        provider: Provider name (NVIDIA, OPENAI, ANTHROPIC)
        key: The API key to verify
    
    Returns:
        tuple: (is_valid: bool, message: str)
    """
    try:
        if provider == "NVIDIA":
            client = OpenAI(api_key=key, base_url="https://integrate.api.nvidia.com/v1")
            try:
                client.models.list()
                return True, "Valid"
            except AuthenticationError:
                return False, "Invalid API Key"
            except Exception as e:
                return False, f"Connection error: {str(e)}"
        
        elif provider == "OPENAI":
            client = OpenAI(api_key=key)
            try:
                client.models.list()
                return True, "Valid"
            except AuthenticationError:
                return False, "Invalid API Key"
            except Exception as e:
                return False, f"Connection error: {str(e)}"
        
        elif provider == "ANTHROPIC":
            if key.startswith("sk-ant-"):
                return True, "Format valid"
            else:
                return False, "Must start with sk-ant-"
        
        else:
            return True, "OK"
    
    except Exception as e:
        return False, f"Error: {str(e)}"


async def execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /key command.
    Prompts user to select a provider and enter their API key.
    Verifies the key and saves to .env file.
    
    Args:
        args: Command arguments (unused for /key)
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    console.print(f"\n[{THEME_COLOR}]Select Provider:[/{THEME_COLOR}]")
    
    # Use radiolist dialog for arrow key navigation (async version)
    dialog_style = Style.from_dict({
        "dialog": "bg:#1a1a1a",
        "dialog.body": "bg:#1a1a1a #ff0000",
        "dialog frame.label": "#ff0000",
        "dialog.shadow": "bg:#000000",
        "radiolist": "#ff0000",
        "radio-selected": "bg:#ff0000 #000000",
        "radio-checked": "#ff0000 bold",
    })
    
    result = await radiolist_dialog(
        title="API Key Setup",
        text="Use arrow keys to select, Enter to confirm:",
        values=[
            ("NVIDIA", "NVIDIA"),
            ("OPENAI", "OPENAI"),
            ("ANTHROPIC", "ANTHROPIC"),
        ],
        style=dialog_style,
    ).run_async()
    
    if result is None:
        console.print("[dim]Cancelled[/dim]")
        return
    
    provider_name = result
    env_key = f"{provider_name}_API_KEY"
    
    api_key = console.input(f"[{THEME_COLOR}]Enter {provider_name} API key:[/{THEME_COLOR}] ").strip()
    if not api_key:
        console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
        return
    
    console.print(f"\n[dim]Verifying key with {provider_name}...[/dim]")
    is_valid, msg = verify_api_key(provider_name, api_key)
    
    if not is_valid:
        console.print(f"[{ACCENT_COLOR}][x] Authentication failed: {msg}[/{ACCENT_COLOR}]")
        return
    
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("# RED SHINOBI Environment Configuration\n")
    set_key(env_path, env_key, api_key)
    load_dotenv(override=True)
    config.API_KEYS[provider_name.lower()] = api_key
    config.reload_keys()
    console.print(f"[green][ok] {provider_name} API key saved[/green]\n")

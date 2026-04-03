"""
RED SHINOBI Model Commands Module

Handles the /models and /system commands for model management.
Supports dynamic model discovery via catalog (OpenAI-compatible endpoints).
"""

import os
from typing import List

from rich.console import Console
from rich.table import Table
from prompt_toolkit import PromptSession

from red_shinobi.core import brain, config
from red_shinobi.core.mcp_client import MCPManager
from red_shinobi.core.nvidia_catalog import (
    MODEL_CATALOG,
    verify_model,
    update_verification,
)
from red_shinobi.commands.auth_cmds import arrow_select

console = Console()
THEME_COLOR = "red"
ACCENT_COLOR = "red"


def get_available_models() -> List[str]:
    """
    Get models from MODEL_CATALOG that have valid keys configured.
    Used by file_cmds for compatibility.
    
    Returns:
        List of catalog model IDs with valid credentials
    """
    available = []
    for model_id, entry in MODEL_CATALOG.items():
        api_key_env = entry.get("api_key_env", "")
        endpoint_type = entry.get("endpoint_type", "")
        
        # Local endpoints don't need keys
        if endpoint_type == "local":
            available.append(model_id)
            continue
        
        # Check if key is configured
        if api_key_env and config.get_env_key(api_key_env):
            available.append(model_id)
    
    return available


async def execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /models command.
    
    Shows catalog entries only.
    """
    if not MODEL_CATALOG:
        console.print(f"\n[{ACCENT_COLOR}][x] Catalog is empty.[/{ACCENT_COLOR}]")
        console.print("[dim]Use /key to add models from providers[/dim]\n")
        return
    
    table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
    table.add_column("Model ID", style="bold", max_width=50)
    table.add_column("Endpoint", justify="center")
    table.add_column("Key?", justify="center")
    table.add_column("Status", justify="center")
    
    entries = list(MODEL_CATALOG.items())
    for model_id, entry in entries[:20]:
        endpoint_type = entry.get("endpoint_type", "?")
        api_key_env = entry.get("api_key_env", "")
        has_key = config.get_env_key(api_key_env) or endpoint_type == "local"
        key_display = "[green]✓[/green]" if has_key else "[red]✗[/red]"
        
        # Status based on verification
        ok_status = entry.get("ok")
        if ok_status is True:
            status_display = f"[green]{entry.get('latency_ms', 0)}ms[/green]"
        elif ok_status is False:
            status_display = "[red]fail[/red]"
        else:
            status_display = "[dim]-[/dim]"
        
        table.add_row(
            model_id[:50],
            endpoint_type,
            key_display,
            status_display
        )
    
    if len(entries) > 20:
        table.add_row(f"[dim]... and {len(entries) - 20} more[/dim]", "", "", "")
    
    console.print("\n")
    console.print(table)
    console.print(f"\n[dim]Total: {len(MODEL_CATALOG)} models[/dim]")
    console.print(f"[dim]Use /refresh to verify models[/dim]\n")


async def system_execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /system command.
    Updates the system prompt for a specific model.
    
    Usage:
        /system <model_name> <new_system_prompt>
    
    Args:
        args: The arguments containing model name and new prompt
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    # If no args, show interactive model picker then ask for prompt
    if not args:
        model_ids = list(MODEL_CATALOG.keys())
        if not model_ids:
            console.print(f"[{ACCENT_COLOR}][x] No models in catalog. Run /key first.[/{ACCENT_COLOR}]")
            return

        options = ["← Back"] + model_ids
        chosen = await arrow_select(
            "Select model to set system prompt for (↑↓ navigate, Enter confirm, Esc cancel):",
            options
        )

        if chosen is None or chosen == "← Back":
            console.print("[dim]Cancelled[/dim]")
            return

        model_name = chosen
        console.print(f"[dim]Model: {model_name}[/dim]")
        new_prompt = await session.prompt_async("New system prompt > ")
        new_prompt = new_prompt.strip()
        if not new_prompt:
            console.print("[dim]Cancelled — prompt cannot be empty[/dim]")
            return
    else:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            console.print(f"[{ACCENT_COLOR}][x] Usage: /system <model> <new_prompt>[/{ACCENT_COLOR}]")
            return
        model_name = parts[0]
        new_prompt = parts[1]
    
    if model_name not in MODEL_CATALOG and model_name not in brain.MODEL_REGISTRY:
        console.print(f"[{ACCENT_COLOR}][x] Model '{model_name}' not found.[/{ACCENT_COLOR}]")
        if MODEL_CATALOG:
            console.print(f"[dim]Run /models to see {len(MODEL_CATALOG)} available models[/dim]")
        return
    
    # Create a MODEL_REGISTRY entry if the model only exists in catalog
    if model_name not in brain.MODEL_REGISTRY:
        brain.MODEL_REGISTRY[model_name] = {
            "api_model_id": model_name,
            "system_prompt": new_prompt
        }
    else:
        brain.MODEL_REGISTRY[model_name]["system_prompt"] = new_prompt
    
    console.print(f"[green][ok] Updated system prompt for {model_name}[/green]\n")


async def info_execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /info command.
    Shows detailed information about a specific model.
    
    Usage:
        /info <model_name>
    
    Args:
        args: The model name to get info about
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    # If no args, show interactive model picker
    if not args:
        model_ids = list(MODEL_CATALOG.keys())
        if not model_ids:
            console.print(f"[{ACCENT_COLOR}][x] No models in catalog. Run /key first.[/{ACCENT_COLOR}]")
            return

        options = ["← Back"] + model_ids
        chosen = await arrow_select(
            "Select model to inspect (↑↓ navigate, Enter confirm, Esc cancel):",
            options
        )

        if chosen is None or chosen == "← Back":
            console.print("[dim]Cancelled[/dim]")
            return

        model_name = chosen
    else:
        model_name = args.strip()
    
    # Check MODEL_CATALOG first (covers all user-added models via /key)
    if model_name in MODEL_CATALOG:
        entry = MODEL_CATALOG[model_name]
        console.print(f"\n[{THEME_COLOR}]Model: {model_name}[/{THEME_COLOR}]")
        console.print(f"[dim]Endpoint : {entry.get('base_url', 'N/A')}[/dim]")
        console.print(f"[dim]Key env  : {entry.get('api_key_env', 'N/A')}[/dim]")
        console.print(f"[dim]Type     : {entry.get('endpoint_type', 'N/A')}[/dim]")
        ok = entry.get("ok")
        if ok is True:
            console.print(f"[dim]Status   : [green]verified ({entry.get('latency_ms')}ms)[/green][/dim]")
        elif ok is False:
            console.print(f"[dim]Status   : [red]failed — {entry.get('error', '')}[/red][/dim]")
        else:
            console.print(f"[dim]Status   : not yet verified (run /refresh)[/dim]")
        if model_name in brain.MODEL_REGISTRY:
            sp = brain.MODEL_REGISTRY[model_name].get("system_prompt", "")
            if sp:
                console.print(f"\n[{THEME_COLOR}]System Prompt:[/{THEME_COLOR}]")
                console.print(f"[dim]{sp}[/dim]")
        console.print()
        return
    
    # Fallback: legacy hardcoded MODEL_REGISTRY entries
    if model_name in brain.MODEL_REGISTRY:
        model_info = brain.MODEL_REGISTRY[model_name]
        console.print(f"\n[{THEME_COLOR}]Model: {model_name}[/{THEME_COLOR}]")
        console.print(f"[dim]API ID: {model_info.get('api_model_id', 'N/A')}[/dim]")
        console.print(f"\n[{THEME_COLOR}]System Prompt:[/{THEME_COLOR}]")
        console.print(f"[dim]{model_info.get('system_prompt', 'No prompt set')}[/dim]\n")
        return
    
    console.print(f"[{ACCENT_COLOR}][x] Model '{model_name}' not found.[/{ACCENT_COLOR}]")
    console.print(f"[dim]Run /models to see available models[/dim]\n")

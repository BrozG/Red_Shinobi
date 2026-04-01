"""
RED SHINOBI Model Commands Module

Handles the /models and /system commands for model management.
Supports dynamic model discovery via NVIDIA catalog.
"""

import os
from datetime import datetime
from typing import List

from rich.console import Console
from rich.table import Table
from prompt_toolkit import PromptSession

from red_shinobi.core import brain, config
from red_shinobi.core.mcp_client import MCPManager
from red_shinobi.core.nvidia_catalog import (
    MODEL_CATALOG,
    fetch_catalog,
    verify_model,
    add_to_catalog,
    update_verification,
    clear_catalog,
)

console = Console()
THEME_COLOR = "red"
ACCENT_COLOR = "red"


def get_available_models() -> List[str]:
    """
    Get models that are actually available based on configured API keys.
    
    Returns:
        List of available model names
    """
    available = []
    nvidia_key = os.getenv("NVIDIA_API_KEY")
    
    if nvidia_key:
        for model_name in brain.MODEL_REGISTRY.keys():
            available.append(model_name)
    
    return available


async def cmd_models_refresh(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Refresh the model catalog by fetching from all configured NVIDIA endpoints.
    """
    console.print(f"\n[{THEME_COLOR}]Refreshing model catalog...[/{THEME_COLOR}]")
    
    clear_catalog()
    
    # Define endpoints to check
    endpoints = []
    
    # Cloud endpoint (always available)
    cloud_base = config.NVIDIA_CLOUD_BASE
    cloud_key = config.get_env_key("NVIDIA_API_KEY")
    if cloud_key:
        endpoints.append(("cloud", cloud_base, "NVIDIA_API_KEY"))
    else:
        console.print("[yellow]⚠ NVIDIA_API_KEY not set, skipping cloud endpoint[/yellow]")
    
    # Partner endpoint (optional)
    partner_base = config.NVIDIA_PARTNER_BASE
    if partner_base:
        partner_key = config.get_env_key("NVIDIA_PARTNER_KEY")
        if partner_key:
            endpoints.append(("partner", partner_base, "NVIDIA_PARTNER_KEY"))
        else:
            console.print("[yellow]⚠ NVIDIA_PARTNER_KEY not set, skipping partner endpoint[/yellow]")
    
    # Local endpoint (optional, key not required)
    local_base = config.NVIDIA_LOCAL_BASE
    if local_base:
        endpoints.append(("local", local_base, "NVIDIA_LOCAL_KEY"))
    
    if not endpoints:
        console.print(f"[{ACCENT_COLOR}][x] No endpoints configured. Set NVIDIA_API_KEY.[/{ACCENT_COLOR}]")
        return
    
    total_models = 0
    
    for endpoint_type, base_url, key_env in endpoints:
        api_key = config.get_env_key(key_env)
        console.print(f"[dim]Fetching from {endpoint_type}: {base_url}...[/dim]")
        
        try:
            model_ids = await fetch_catalog(base_url, api_key)
            for model_id in model_ids:
                add_to_catalog(model_id, base_url, endpoint_type, key_env)
                total_models += 1
            console.print(f"[green]✓ {endpoint_type}: {len(model_ids)} models[/green]")
        except Exception as e:
            console.print(f"[{ACCENT_COLOR}][x] {endpoint_type}: {e}[/{ACCENT_COLOR}]")
    
    console.print(f"\n[green]Total: {total_models} models in catalog[/green]")
    
    # Print table
    if MODEL_CATALOG:
        table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
        table.add_column("Model ID", style="bold", max_width=50)
        table.add_column("Endpoint", justify="center")
        table.add_column("Key?", justify="center")
        
        for model_id, entry in list(MODEL_CATALOG.items())[:20]:
            has_key = "✓" if config.get_env_key(entry["api_key_env"]) or entry["endpoint_type"] == "local" else "✗"
            key_style = "green" if has_key == "✓" else "red"
            table.add_row(
                model_id[:50],
                entry["endpoint_type"],
                f"[{key_style}]{has_key}[/{key_style}]"
            )
        
        if len(MODEL_CATALOG) > 20:
            table.add_row(f"... and {len(MODEL_CATALOG) - 20} more", "", "")
        
        console.print(table)
    console.print()


async def cmd_models_verify(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Verify models in the catalog by sending ping requests.
    """
    if not MODEL_CATALOG:
        console.print(f"[{ACCENT_COLOR}][x] Catalog empty. Run /models refresh first.[/{ACCENT_COLOR}]")
        return
    
    console.print(f"\n[{THEME_COLOR}]Verifying {len(MODEL_CATALOG)} models...[/{THEME_COLOR}]")
    
    results = []
    for model_id, entry in MODEL_CATALOG.items():
        api_key = config.get_env_key(entry["api_key_env"])
        
        if entry["endpoint_type"] != "local" and not api_key:
            console.print(f"[yellow]⚠ Skipping {model_id}: missing {entry['api_key_env']}[/yellow]")
            continue
        
        console.print(f"[dim]Verifying {model_id}...[/dim]", end="")
        ok, latency, error = await verify_model(entry["base_url"], api_key, model_id)
        update_verification(model_id, ok, latency, error)
        
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f" {status} {latency}ms")
        results.append((model_id, ok, latency, error))
    
    # Print summary table
    table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
    table.add_column("Model ID", style="bold", max_width=50)
    table.add_column("Status", justify="center")
    table.add_column("Latency", justify="right")
    table.add_column("Error", max_width=30)
    
    for model_id, ok, latency, error in results[:20]:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        err_display = (error[:27] + "...") if error and len(error) > 30 else (error or "")
        table.add_row(model_id[:50], status, f"{latency}ms", err_display)
    
    console.print("\n")
    console.print(table)
    console.print()


async def execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /models command.
    
    Subcommands:
        /models           - Show available models
        /models refresh   - Fetch models from NVIDIA endpoints
        /models verify    - Verify models are callable
    """
    subcommand = args.strip().lower()
    
    if subcommand == "refresh":
        await cmd_models_refresh(args, session, mcp_manager, session_history)
        return
    
    if subcommand == "verify":
        await cmd_models_verify(args, session, mcp_manager, session_history)
        return
    
    # Default: show available models
    available_models = get_available_models()
    
    if not available_models and not MODEL_CATALOG:
        console.print(f"\n[{ACCENT_COLOR}][x] No models available[/{ACCENT_COLOR}]")
        console.print("[dim]Configure API key with /key, then run /models refresh[/dim]\n")
        return
    
    table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
    table.add_column("Model", style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Status", justify="center")
    
    # Show static models
    for model_name in available_models:
        model_info = brain.MODEL_REGISTRY.get(model_name, {})
        table.add_row(
            model_name,
            model_info.get("api_model_id", "N/A"),
            "[green]ready[/green]"
        )
    
    console.print("\n")
    console.print(table)
    
    # Show catalog count if populated
    if MODEL_CATALOG:
        verified = sum(1 for e in MODEL_CATALOG.values() if e.get("ok") is True)
        console.print(f"\n[dim]Catalog: {len(MODEL_CATALOG)} models ({verified} verified)[/dim]")
        console.print("[dim]Use /models refresh to update, /models verify to test[/dim]")
    else:
        console.print("\n[dim]Tip: Run /models refresh to discover all NVIDIA models[/dim]")
    
    console.print("\n")


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
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        console.print(f"[{ACCENT_COLOR}][x] Usage: /system <model> <new_prompt>[/{ACCENT_COLOR}]")
        return
    
    model_name = parts[0]
    new_prompt = parts[1]
    
    if model_name not in brain.MODEL_REGISTRY:
        console.print(f"[{ACCENT_COLOR}][x] Model '{model_name}' not found[/{ACCENT_COLOR}]")
        available = list(brain.MODEL_REGISTRY.keys())
        if len(available) > 5:
            displayed = available[:5] + [f"... and {len(available) - 5} more"]
        else:
            displayed = available
        console.print(f"[dim]Available: {', '.join(displayed)}[/dim]")
        return
    
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
    if not args:
        console.print(f"[{ACCENT_COLOR}][x] Usage: /info <model>[/{ACCENT_COLOR}]")
        return
    
    model_name = args.strip()
    
    if model_name not in brain.MODEL_REGISTRY:
        console.print(f"[{ACCENT_COLOR}][x] Model '{model_name}' not found[/{ACCENT_COLOR}]")
        return
    
    model_info = brain.MODEL_REGISTRY[model_name]
    
    console.print(f"\n[{THEME_COLOR}]Model: {model_name}[/{THEME_COLOR}]")
    console.print(f"[dim]API ID: {model_info.get('api_model_id', 'N/A')}[/dim]")
    console.print(f"\n[{THEME_COLOR}]System Prompt:[/{THEME_COLOR}]")
    console.print(f"[dim]{model_info.get('system_prompt', 'No prompt set')}[/dim]\n")

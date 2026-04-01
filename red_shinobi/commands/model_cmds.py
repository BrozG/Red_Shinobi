"""
RED SHINOBI Model Commands Module

Handles the /models and /system commands for model management.
Supports dynamic model discovery via catalog (OpenAI-compatible endpoints).
"""

import os
import asyncio
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
    add_custom_model,
)

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


async def cmd_models_add(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Add models from a custom OpenAI-compatible endpoint.
    Usage: /models add <base_url> <api_key_env>
    """
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        console.print(f"[{ACCENT_COLOR}]Usage: /models add <base_url> <api_key_env>[/{ACCENT_COLOR}]")
        console.print("[dim]Example: /models add https://api.openai.com/v1 OPENAI_API_KEY[/dim]")
        return
    
    base_url = parts[0]
    api_key_env = parts[1]
    
    # Check if it looks like a local endpoint
    is_local = "localhost" in base_url or "127.0.0.1" in base_url
    
    # Resolve API key
    api_key = config.get_env_key(api_key_env)
    
    if not is_local and not api_key:
        console.print(f"[yellow]⚠ {api_key_env} not set. Set it first or the endpoint may reject requests.[/yellow]")
        console.print(f"[dim]For local endpoints, this is usually okay.[/dim]")
        return
    
    console.print(f"\n[{THEME_COLOR}]Fetching models from {base_url}...[/{THEME_COLOR}]")
    
    try:
        model_ids = await fetch_catalog(base_url, api_key)
        
        if not model_ids:
            console.print("[yellow]No models returned.[/yellow]")
            return
        
        for model_id in model_ids:
            add_custom_model(model_id, base_url, api_key_env, endpoint_type="custom", source="add")
        
        console.print(f"[green]✓ Added {len(model_ids)} models from {base_url}[/green]")
        
        # Show preview
        table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
        table.add_column("Model ID", style="bold", max_width=60)
        
        for model_id in model_ids[:10]:
            table.add_row(model_id)
        
        if len(model_ids) > 10:
            table.add_row(f"[dim]... and {len(model_ids) - 10} more[/dim]")
        
        console.print(table)
        console.print()
        
    except Exception as e:
        console.print(f"[{ACCENT_COLOR}][x] Failed: {e}[/{ACCENT_COLOR}]")


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
    
    # Build endpoints list from environment
    endpoints = []
    
    # Cloud endpoint (if NVIDIA_API_KEY set)
    if config.get_env_key("NVIDIA_API_KEY"):
        cloud_base = config.NVIDIA_CLOUD_BASE
        endpoints.append(("cloud", cloud_base, "NVIDIA_API_KEY"))
    
    # Partner endpoint (if both base and key set)
    partner_base = config.NVIDIA_PARTNER_BASE
    partner_key = config.get_env_key("NVIDIA_PARTNER_KEY")
    if partner_base and partner_key:
        endpoints.append(("partner", partner_base, "NVIDIA_PARTNER_KEY"))
    
    # Local endpoint (if base set, key optional)
    local_base = config.NVIDIA_LOCAL_BASE
    if local_base:
        endpoints.append(("local", local_base, "NVIDIA_LOCAL_KEY"))
    
    if not endpoints:
        console.print(f"[{ACCENT_COLOR}][x] No endpoints configured.[/{ACCENT_COLOR}]")
        console.print("[dim]Set NVIDIA_API_KEY to enable cloud endpoint.[/dim]")
        return
    
    total_models = 0
    
    for endpoint_type, base_url, key_env in endpoints:
        api_key = config.get_env_key(key_env)
        console.print(f"[dim]Fetching from {endpoint_type}: {base_url}...[/dim]")
        
        try:
            model_ids = await fetch_catalog(base_url, api_key)
            for model_id in model_ids:
                add_to_catalog(model_id, base_url, endpoint_type, key_env, source="refresh")
                total_models += 1
            console.print(f"[green]✓ {endpoint_type}: {len(model_ids)} models[/green]")
        except Exception as e:
            console.print(f"[{ACCENT_COLOR}][x] {endpoint_type}: {e}[/{ACCENT_COLOR}]")
            continue
    
    console.print(f"\n[green]Total: {total_models} models in catalog[/green]\n")


async def cmd_models_verify(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Verify models in the catalog by sending ping requests.
    Usage: /models verify [--limit N] [--filter substring]
    """
    if not MODEL_CATALOG:
        console.print(f"[{ACCENT_COLOR}][x] Catalog empty. Run /models refresh first.[/{ACCENT_COLOR}]")
        return
    
    # Parse args
    parts = args.strip().split()
    limit = None
    filter_str = None
    
    i = 0
    while i < len(parts):
        if parts[i] == "--limit" and i + 1 < len(parts):
            try:
                limit = int(parts[i + 1])
                i += 2
            except ValueError:
                console.print(f"[yellow]Invalid --limit value, ignoring[/yellow]")
                i += 2
        elif parts[i] == "--filter" and i + 1 < len(parts):
            filter_str = parts[i + 1]
            i += 2
        else:
            i += 1
    
    # Filter catalog
    to_verify = []
    for model_id, entry in MODEL_CATALOG.items():
        if filter_str and filter_str not in model_id:
            continue
        to_verify.append(model_id)
        if limit and len(to_verify) >= limit:
            break
    
    if not to_verify:
        console.print("[yellow]No models match filter.[/yellow]")
        return
    
    console.print(f"\n[{THEME_COLOR}]Verifying {len(to_verify)} models...[/{THEME_COLOR}]")
    
    results = []
    for idx, model_id in enumerate(to_verify):
        entry = MODEL_CATALOG[model_id]
        api_key_env = entry["api_key_env"]
        endpoint_type = entry["endpoint_type"]
        base_url = entry["base_url"]
        
        api_key = config.get_env_key(api_key_env) if api_key_env else None
        
        if endpoint_type != "local" and not api_key:
            console.print(f"[yellow]⚠ Skipping {model_id}: missing {api_key_env}[/yellow]")
            continue
        
        console.print(f"[dim]{idx+1}/{len(to_verify)} Verifying {model_id[:50]}...[/dim]", end="")
        
        try:
            ok, latency, error = await verify_model(base_url, api_key, model_id)
            update_verification(model_id, ok, latency, error)
            
            # Handle rate limiting with backoff
            if error and "429" in str(error):
                console.print(f" [yellow]429 (rate limit), sleeping...[/yellow]")
                await asyncio.sleep(1)
            else:
                status = "[green]✓[/green]" if ok else "[red]✗[/red]"
                console.print(f" {status} {latency}ms")
            
            results.append((model_id, ok, latency, error))
            
        except Exception as e:
            console.print(f" [red]✗ {str(e)[:30]}[/red]")
            update_verification(model_id, False, 0, str(e)[:200])
            results.append((model_id, False, 0, str(e)[:200]))
    
    # Print summary table
    if results:
        table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
        table.add_column("Model ID", style="bold", max_width=50)
        table.add_column("Status", justify="center")
        table.add_column("Latency", justify="right")
        table.add_column("Error", max_width=30)
        
        for model_id, ok, latency, error in results[:20]:
            status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
            err_display = (error[:27] + "...") if error and len(error) > 30 else (error or "")
            table.add_row(model_id[:50], status, f"{latency}ms", err_display)
        
        if len(results) > 20:
            table.add_row(f"[dim]... and {len(results) - 20} more[/dim]", "", "", "")
        
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
        /models           - Show catalog entries only
        /models refresh   - Fetch models from NVIDIA endpoints
        /models add       - Add custom OpenAI-compatible endpoint
        /models verify    - Verify models are callable
    """
    subcommand = args.strip().split()[0].lower() if args.strip() else ""
    remaining_args = args.strip().split(maxsplit=1)[1] if len(args.strip().split()) > 1 else ""
    
    if subcommand == "refresh":
        await cmd_models_refresh(remaining_args, session, mcp_manager, session_history)
        return
    
    if subcommand == "verify":
        await cmd_models_verify(remaining_args, session, mcp_manager, session_history)
        return
    
    if subcommand == "add":
        await cmd_models_add(remaining_args, session, mcp_manager, session_history)
        return
    
    # Default: show catalog entries only
    if not MODEL_CATALOG:
        console.print(f"\n[{ACCENT_COLOR}][x] Catalog is empty.[/{ACCENT_COLOR}]")
        console.print("[dim]Run /models refresh to discover models[/dim]")
        console.print("[dim]Or /models add <base_url> <api_key_env> to add custom endpoint[/dim]\n")
        return
    
    table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
    table.add_column("Model ID", style="bold", max_width=50)
    table.add_column("Endpoint", justify="center")
    table.add_column("Key?", justify="center")
    table.add_column("OK?", justify="center")
    
    entries = list(MODEL_CATALOG.items())
    for model_id, entry in entries[:20]:
        endpoint_type = entry.get("endpoint_type", "?")
        api_key_env = entry.get("api_key_env", "")
        has_key = config.get_env_key(api_key_env) or endpoint_type == "local"
        key_display = "[green]✓[/green]" if has_key else "[red]✗[/red]"
        
        ok_status = entry.get("ok")
        if ok_status is True:
            ok_display = "[green]✓[/green]"
        elif ok_status is False:
            ok_display = "[red]✗[/red]"
        else:
            ok_display = ""
        
        table.add_row(
            model_id[:50],
            endpoint_type,
            key_display,
            ok_display
        )
    
    if len(entries) > 20:
        table.add_row(f"[dim]... and {len(entries) - 20} more[/dim]", "", "", "")
    
    console.print("\n")
    console.print(table)
    
    verified = sum(1 for e in MODEL_CATALOG.values() if e.get("ok") is True)
    console.print(f"\n[dim]Total: {len(MODEL_CATALOG)} models ({verified} verified)[/dim]")
    console.print("[dim]Use /models verify to test, /models add to add custom endpoint[/dim]")
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

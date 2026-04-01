"""
RED SHINOBI Refresh Commands Module

Handles the /refresh command for verifying models in the catalog.
Only tests existing models, does not fetch new ones.
"""

import asyncio
from rich.console import Console
from prompt_toolkit import PromptSession

from red_shinobi.core import config
from red_shinobi.core.mcp_client import MCPManager
from red_shinobi.core.nvidia_catalog import (
    MODEL_CATALOG,
    verify_model,
    update_verification,
)

console = Console()
THEME_COLOR = "red"
ACCENT_COLOR = "red"


async def execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /refresh command.
    Verifies models already in the catalog by pinging them.
    Does NOT fetch new models from providers.
    
    Usage:
        /refresh           - Verify all models in catalog
        /refresh --limit N - Verify only first N models
    
    Args:
        args: Optional arguments (--limit N)
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    if not MODEL_CATALOG:
        console.print(f"\n[{ACCENT_COLOR}][x] Catalog is empty.[/{ACCENT_COLOR}]")
        console.print("[dim]Use /key to add models from providers[/dim]\n")
        return
    
    # Parse args
    parts = args.strip().split()
    limit = None
    
    i = 0
    while i < len(parts):
        if parts[i] == "--limit" and i + 1 < len(parts):
            try:
                limit = int(parts[i + 1])
                i += 2
            except ValueError:
                console.print(f"[yellow]Invalid --limit value, ignoring[/yellow]")
                i += 2
        else:
            i += 1
    
    # Get models to verify
    to_verify = list(MODEL_CATALOG.keys())
    if limit:
        to_verify = to_verify[:limit]
    
    console.print(f"\n[{THEME_COLOR}]Verifying {len(to_verify)} models in catalog...[/{THEME_COLOR}]")
    console.print(f"[dim]This only tests existing models, doesn't fetch new ones[/dim]\n")
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    for idx, model_id in enumerate(to_verify):
        entry = MODEL_CATALOG[model_id]
        api_key_env = entry["api_key_env"]
        endpoint_type = entry["endpoint_type"]
        base_url = entry["base_url"]
        
        api_key = config.get_env_key(api_key_env) if api_key_env else None
        
        if endpoint_type != "local" and not api_key:
            console.print(f"[yellow]⚠ Skipping {model_id[:50]}: missing {api_key_env}[/yellow]")
            skip_count += 1
            continue
        
        console.print(f"[dim]{idx+1}/{len(to_verify)} Testing {model_id[:50]}...[/dim]", end="")
        
        try:
            ok, latency, error = await verify_model(base_url, api_key, model_id)
            update_verification(model_id, ok, latency, error)
            
            # Handle rate limiting with backoff
            if error and "429" in str(error):
                console.print(f" [yellow]429 (rate limit)[/yellow]")
                await asyncio.sleep(1)
                fail_count += 1
            # Handle BadRequest (400) - mark as incompatible
            elif error and ("400" in str(error) or "BadRequest" in str(error)):
                console.print(f" [yellow]✗ incompatible[/yellow]")
                fail_count += 1
            elif ok:
                console.print(f" [green]✓ {latency}ms[/green]")
                success_count += 1
            else:
                console.print(f" [red]✗[/red]")
                fail_count += 1
            
        except Exception as e:
            console.print(f" [red]✗ {str(e)[:30]}[/red]")
            update_verification(model_id, False, 0, str(e)[:200])
            fail_count += 1
    
    # Print summary
    console.print(f"\n[green]✓ {success_count} working[/green]  [red]✗ {fail_count} failed[/red]", end="")
    if skip_count > 0:
        console.print(f"  [yellow]⚠ {skip_count} skipped[/yellow]")
    else:
        console.print()
    console.print(f"[dim]Run /models to see full catalog with status[/dim]")
    console.print(f"[dim]Note: Some models may be incompatible with standard chat API[/dim]\n")

"""
RED SHINOBI Model Catalog

Generic OpenAI-compatible model catalog for dynamic discovery and verification.
Supports any OpenAI-compatible endpoint (NVIDIA, OpenAI, Ollama, local servers, etc.).

Usage:
    # Auto-discover models from an endpoint
    await fetch_catalog('https://api.openai.com/v1', api_key)
    
    # Manually add custom models
    add_custom_model('gpt-4', 'https://api.openai.com/v1', 'OPENAI_API_KEY', 'openai')
    add_custom_model('llama2', 'http://localhost:11434/v1', '', 'local')
    
    # Verify a model works
    ok, latency, error = await verify_model(base_url, api_key, model_id)
"""

import time
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import aiohttp

# Global catalog: {model_id: {base_url, api_key_env, endpoint_type, ok, latency_ms, error, last_checked, source}}
MODEL_CATALOG: Dict[str, Dict[str, Any]] = {}


async def fetch_catalog(base_url: str, api_key: Optional[str]) -> List[str]:
    """
    Fetch available models from an OpenAI-compatible /v1/models endpoint.
    
    Args:
        base_url: Base URL of the API (e.g., https://integrate.api.nvidia.com/v1)
        api_key: API key for authentication (can be None for local endpoints)
    
    Returns:
        List of model IDs
    
    Raises:
        RuntimeError: If the request fails
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
    # Ensure base_url ends with /v1 for the models endpoint
    models_url = base_url.rstrip("/")
    if not models_url.endswith("/v1"):
        models_url = f"{models_url}/v1"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{models_url}/models", headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            txt = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"{resp.status} {txt[:500]}")
            data = json.loads(txt)
            # OpenAI-style returns {"data":[{"id":...}, ...]}
            return [m["id"] for m in data.get("data", [])]


async def verify_model(base_url: str, api_key: Optional[str], model_id: str) -> Tuple[bool, int, Optional[str]]:
    """
    Verify a model is callable by sending a minimal ping request.
    Never raises - always returns a tuple.
    
    Args:
        base_url: Base URL of the API
        api_key: API key for authentication (None for endpoints that don't require auth)
        model_id: The model ID to verify
    
    Returns:
        Tuple of (ok: bool, latency_ms: int, error: Optional[str])
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    headers["Content-Type"] = "application/json"
    
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1
    }
    
    # Ensure base_url ends with /v1
    completions_url = base_url.rstrip("/")
    if not completions_url.endswith("/v1"):
        completions_url = f"{completions_url}/v1"
    
    t0 = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{completions_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                txt = await resp.text()
                latency = int((time.time() - t0) * 1000)
                ok = resp.status == 200
                err = None if ok else f"{resp.status} {txt[:200]}"
                return ok, latency, err
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return False, latency, str(e)[:200]


def add_to_catalog(
    model_id: str,
    base_url: str,
    endpoint_type: str,
    api_key_env: str,
    source: str = "refresh"
) -> None:
    """
    Add or update a model in the catalog (used by /models refresh).
    
    Args:
        model_id: The model identifier
        base_url: Base URL for this model's endpoint
        endpoint_type: One of 'cloud', 'partner', 'local', 'custom', etc.
        api_key_env: Environment variable name for the API key
        source: How this entry was added (default: 'refresh')
    """
    MODEL_CATALOG[model_id] = {
        "base_url": base_url,
        "endpoint_type": endpoint_type,
        "api_key_env": api_key_env,
        "ok": None,
        "latency_ms": None,
        "error": None,
        "last_checked": datetime.now().isoformat(),
        "source": source
    }


def add_custom_model(
    model_id: str,
    base_url: str,
    api_key_env: str = "CUSTOM_API_KEY",
    endpoint_type: str = "custom",
    source: str = "add"
) -> None:
    """
    Manually add a custom OpenAI-compatible model to the catalog.
    Use this for adding models from non-NVIDIA endpoints (OpenAI, Anthropic, local servers, etc.).
    
    Args:
        model_id: The model identifier (e.g., 'gpt-4', 'claude-3-opus')
        base_url: Base URL of the OpenAI-compatible endpoint
        api_key_env: Environment variable name for the API key (default: 'CUSTOM_API_KEY')
        endpoint_type: Type of endpoint (default: 'custom')
        source: How this entry was added (default: 'add')
    
    Example:
        add_custom_model('gpt-4', 'https://api.openai.com/v1', 'OPENAI_API_KEY', 'openai')
        add_custom_model('llama2', 'http://localhost:11434/v1', '', 'local')
    """
    MODEL_CATALOG[model_id] = {
        "base_url": base_url,
        "endpoint_type": endpoint_type,
        "api_key_env": api_key_env,
        "ok": None,
        "latency_ms": None,
        "error": None,
        "last_checked": datetime.now().isoformat(),
        "source": source
    }


def update_verification(model_id: str, ok: bool, latency_ms: int, error: Optional[str]) -> None:
    """
    Update verification results for a model.
    
    Args:
        model_id: The model identifier
        ok: Whether the model responded successfully
        latency_ms: Response latency in milliseconds
        error: Error message if any
    """
    if model_id in MODEL_CATALOG:
        MODEL_CATALOG[model_id].update({
            "ok": ok,
            "latency_ms": latency_ms,
            "error": error,
            "last_checked": datetime.now().isoformat()
        })


def get_first_working_model() -> Optional[str]:
    """
    Get the first model that has ok==True, or first entry if none verified.
    
    Returns:
        Model ID or None if catalog is empty
    """
    if not MODEL_CATALOG:
        return None
    
    # First try to find a verified working model
    for model_id, entry in MODEL_CATALOG.items():
        if entry.get("ok") is True:
            return model_id
    
    # Otherwise return first entry
    return next(iter(MODEL_CATALOG.keys()))


def clear_catalog() -> None:
    """Clear all entries from the catalog."""
    MODEL_CATALOG.clear()

"""
RED SHINOBI Configuration Module

Handles API keys and environment variable loading for all AI providers.
"""

import os
from dotenv import load_dotenv, dotenv_values

load_dotenv()

# =============================================================================
# API KEYS
# =============================================================================

API_KEYS = {
    "nvidia": os.getenv("NVIDIA_API_KEY"),
    "openai": os.getenv("OPENAI_API_KEY"),
    "anthropic": os.getenv("ANTHROPIC_API_KEY"),
}

# =============================================================================
# NVIDIA ENDPOINT CONFIGURATION
# =============================================================================

NVIDIA_CLOUD_BASE = os.getenv("NVIDIA_CLOUD_BASE", "https://integrate.api.nvidia.com/v1")
NVIDIA_PARTNER_BASE = os.getenv("NVIDIA_PARTNER_BASE")
NVIDIA_LOCAL_BASE = os.getenv("NVIDIA_LOCAL_BASE")

# =============================================================================
# PROVIDERS
# =============================================================================

PROVIDERS = {
    "default_planner": {
        "provider": "nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-70b-instruct",
    },
    "planner": {
        "provider": "nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-70b-instruct",
    },
    "text_worker": {
        "provider": "nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-8b-instruct",
    },
    "image_worker": {
        "provider": "nvidia",
        "base_url": "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-xl",
        "model": "stable-diffusion-xl",
    },
}


def get_key(provider_name: str) -> str:
    """
    Securely retrieve API key for the given provider.
    
    Args:
        provider_name: Name of the provider (e.g., 'nvidia', 'openai', 'anthropic')
    
    Returns:
        The API key string
    
    Raises:
        ValueError: If the API key is not configured
    """
    key = API_KEYS.get(provider_name)
    if not key:
        raise ValueError(f"API key not configured for provider: {provider_name}")
    return key


def get_env_key(env_name: str, default: str = None) -> str:
    """
    Get an environment variable value directly from .env file.
    This reads fresh values, not cached os.environ.
    
    Args:
        env_name: Name of the environment variable
        default: Default value if not set
    
    Returns:
        The environment variable value or default
    """
    # Read directly from .env file to get fresh values
    env_path = ".env"
    if os.path.exists(env_path):
        env_values = dotenv_values(env_path)
        value = env_values.get(env_name)
        if value:
            return value
    return os.getenv(env_name, default)


def reload_keys():
    """Reload API keys from .env file after changes."""
    env_path = ".env"
    if os.path.exists(env_path):
        env_values = dotenv_values(env_path)
        API_KEYS["nvidia"] = env_values.get("NVIDIA_API_KEY") or os.getenv("NVIDIA_API_KEY")
        API_KEYS["openai"] = env_values.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        API_KEYS["anthropic"] = env_values.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    else:
        load_dotenv(override=True)
        API_KEYS["nvidia"] = os.getenv("NVIDIA_API_KEY")
        API_KEYS["openai"] = os.getenv("OPENAI_API_KEY")
        API_KEYS["anthropic"] = os.getenv("ANTHROPIC_API_KEY")

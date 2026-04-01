"""
RED SHINOBI Brain Module

Strict 1-on-1 conversation with optional single handoff.
NO group chat. NO infinite loops. Tools are FORCED when available.
"""

import asyncio
import json
import re
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

from openai import AsyncOpenAI, RateLimitError, APIError
from rich.console import Console
from rich import print as rprint

from red_shinobi.core import config
from red_shinobi.core.nvidia_catalog import MODEL_CATALOG

if TYPE_CHECKING:
    from red_shinobi.core.mcp_client import MCPManager

console = Console()

# Default client (will be replaced dynamically per request)
client = AsyncOpenAI(
    base_url=config.PROVIDERS["default_planner"]["base_url"],
    api_key=config.get_key("nvidia") if config.API_KEYS.get("nvidia") else "placeholder"
)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MODEL = "Nemotron-4-340B"
MAX_TOOL_ROUNDS = 5
TEMPERATURE = 0.7
MAX_TOKENS = 1024

# =============================================================================
# MODEL REGISTRY
# =============================================================================

MODEL_REGISTRY: Dict[str, Dict[str, str]] = {
    "Nemotron-4-340B": {
        "api_model_id": "nvidia/nemotron-4-340b-instruct",
        "system_prompt": """You are Nemotron-4-340B, NVIDIA's flagship AI model.

TOOL USAGE (MANDATORY):
- You have MCP tools available. When asked to perform actions (file ops, searches, etc.), you MUST call the tools.
- Do NOT describe what you would do. Actually CALL the tool functions provided.
- If no tools are needed, just answer directly.

HANDOFF (OPTIONAL):
- If you truly need another model's help, mention them with @ModelName (e.g., "@Codestral-22B").
- Only do this if absolutely necessary."""
    },
    "Llama-3.1-70B": {
        "api_model_id": "meta/llama-3.1-70b-instruct",
        "system_prompt": """You are Llama-3.1-70B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Llama-3.1-8B": {
        "api_model_id": "meta/llama-3.1-8b-instruct",
        "system_prompt": """You are Llama-3.1-8B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Llama-3.1-405B": {
        "api_model_id": "meta/llama-3.1-405b-instruct",
        "system_prompt": """You are Llama-3.1-405B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Llama-3.2-3B": {
        "api_model_id": "meta/llama-3.2-3b-instruct",
        "system_prompt": """You are Llama-3.2-3B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Llama-3.2-1B": {
        "api_model_id": "meta/llama-3.2-1b-instruct",
        "system_prompt": """You are Llama-3.2-1B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Mistral-7B": {
        "api_model_id": "mistralai/mistral-7b-instruct-v0.3",
        "system_prompt": """You are Mistral-7B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Mixtral-8x7B": {
        "api_model_id": "mistralai/mixtral-8x7b-instruct-v0.1",
        "system_prompt": """You are Mixtral-8x7B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Mixtral-8x22B": {
        "api_model_id": "mistralai/mixtral-8x22b-instruct-v0.1",
        "system_prompt": """You are Mixtral-8x22B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Codestral-22B": {
        "api_model_id": "mistralai/codestral-22b-instruct-v0.1",
        "system_prompt": """You are Codestral-22B, a code specialist in RED SHINOBI.
Use MCP tools for file and code operations. Mention @ModelName only if you need another model's help."""
    },
    "Gemma-2-9B": {
        "api_model_id": "google/gemma-2-9b-it",
        "system_prompt": """You are Gemma-2-9B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Gemma-2-27B": {
        "api_model_id": "google/gemma-2-27b-it",
        "system_prompt": """You are Gemma-2-27B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Phi-3-Mini": {
        "api_model_id": "microsoft/phi-3-mini-128k-instruct",
        "system_prompt": """You are Phi-3-Mini in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Phi-3-Small": {
        "api_model_id": "microsoft/phi-3-small-128k-instruct",
        "system_prompt": """You are Phi-3-Small in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Phi-3-Medium": {
        "api_model_id": "microsoft/phi-3-medium-128k-instruct",
        "system_prompt": """You are Phi-3-Medium in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "DeepSeek-Coder-V2": {
        "api_model_id": "deepseek-ai/deepseek-coder-6.7b-instruct",
        "system_prompt": """You are DeepSeek-Coder in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "Qwen2-7B": {
        "api_model_id": "qwen/qwen2-7b-instruct",
        "system_prompt": """You are Qwen2-7B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
    "StarCoder2-15B": {
        "api_model_id": "bigcode/starcoder2-15b",
        "system_prompt": """You are StarCoder2-15B in RED SHINOBI.
Use MCP tools when available. Mention @ModelName only if you need another model's help."""
    },
}


def get_all_model_names() -> List[str]:
    """Return all registered model names."""
    return list(MODEL_REGISTRY.keys())


def is_valid_model(model_name: str) -> bool:
    """Check if model exists in registry (case-insensitive)."""
    if model_name in MODEL_REGISTRY:
        return True
    for name in MODEL_REGISTRY.keys():
        if model_name.lower() == name.lower():
            return True
    return False


def normalize_model_name(model_name: str) -> Optional[str]:
    """Return the exact registry name for a model (case-insensitive match)."""
    if model_name in MODEL_REGISTRY:
        return model_name
    for name in MODEL_REGISTRY.keys():
        if model_name.lower() == name.lower():
            return name
    return None


def extract_mentioned_model(text: str) -> Optional[str]:
    """Extract first valid @ModelName from text."""
    pattern = r'@([\w\-\.]+)'
    matches = re.findall(pattern, text)
    for match in matches:
        normalized = normalize_model_name(match)
        if normalized:
            return normalized
    return None


def human_interrupt(
    chat_history: Optional[List[Dict[str, Any]]],
    user_message: str
) -> List[Dict[str, Any]]:
    """Inject a human message into conversation."""
    if chat_history is None:
        chat_history = []
    chat_history.append({"role": "user", "content": f"[HUMAN]: {user_message}"})
    return chat_history


# =============================================================================
# DYNAMIC ENDPOINT RESOLUTION
# =============================================================================

def resolve_model_endpoint(model_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Resolve base_url and api_key for a model from the catalog.
    Falls back to MODEL_REGISTRY if not in catalog.
    
    Args:
        model_id: The model identifier (can be friendly name or catalog ID)
    
    Returns:
        Tuple of (base_url, api_key, error_message)
        If error_message is set, base_url and api_key will be None.
    """
    # First check if it's in MODEL_CATALOG (dynamic discovery)
    entry = MODEL_CATALOG.get(model_id)
    if entry:
        key = config.get_env_key(entry["api_key_env"])
        if entry["endpoint_type"] != "local" and not key:
            return None, None, f"Missing key {entry['api_key_env']}. Set env or use /key."
        return entry["base_url"], key, None
    
    # Fallback to MODEL_REGISTRY (static models)
    if model_id in MODEL_REGISTRY:
        model_info = MODEL_REGISTRY[model_id]
        api_model_id = model_info.get("api_model_id", "")
        # Check catalog for the api_model_id
        if api_model_id in MODEL_CATALOG:
            entry = MODEL_CATALOG[api_model_id]
            key = config.get_env_key(entry["api_key_env"])
            if entry["endpoint_type"] != "local" and not key:
                return None, None, f"Missing key {entry['api_key_env']}. Set env or use /key."
            return entry["base_url"], key, None
        
        # Use default NVIDIA endpoint
        nvidia_key = config.API_KEYS.get("nvidia")
        if nvidia_key:
            return config.PROVIDERS["default_planner"]["base_url"], nvidia_key, None
        return None, None, "Missing NVIDIA_API_KEY. Set env or use /key nvidia."
    
    return None, None, f"Model {model_id} not in catalog. Run /models refresh."


# =============================================================================
# MCP TOOL FUNCTIONS
# =============================================================================

async def get_mcp_tools_for_llm(mcp_manager: Optional["MCPManager"]) -> Optional[List[Dict[str, Any]]]:
    """Get MCP tools formatted for OpenAI function calling."""
    if mcp_manager is None:
        return None
    
    servers_list = mcp_manager.list_servers()
    if not servers_list:
        return None
    
    active_servers = [
        s["name"] for s in servers_list 
        if s.get("state") == "ready" and s.get("capabilities", {}).get("tools", False)
    ]
    
    if not active_servers:
        return None
    
    formatted_tools: List[Dict[str, Any]] = []
    
    for server_name in active_servers:
        tools_result = await mcp_manager.get_tools(server_name)
        if isinstance(tools_result, str) or not isinstance(tools_result, list):
            continue
        
        for tool in tools_result:
            tool_name = tool.get("name", "")
            tool_desc = tool.get("description", "No description")
            tool_schema = tool.get("inputSchema", {"type": "object", "properties": {}, "required": []})
            
            formatted_tools.append({
                "type": "function",
                "function": {
                    "name": f"{server_name}__{tool_name}",
                    "description": tool_desc,
                    "parameters": tool_schema
                }
            })
    
    return formatted_tools if formatted_tools else None


def extract_tool_result(result: Any) -> str:
    """Extract string content from MCP tool result."""
    if isinstance(result, str):
        return result
    
    if isinstance(result, dict):
        if "content" in result:
            content = result["content"]
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        parts.append(item.get("text", json.dumps(item)))
                    else:
                        parts.append(str(item))
                return "\n".join(parts)
            elif isinstance(content, str):
                return content
            return json.dumps(content, indent=2)
        
        if result.get("isError"):
            return f"Tool Error: {result}"
        
        return json.dumps(result, indent=2)
    
    if isinstance(result, list):
        return json.dumps(result, indent=2)
    
    return str(result)


# =============================================================================
# CHAT WORKER - Single Model Interaction with Tool Support
# =============================================================================

async def chat_worker(
    model_name: str,
    prompt: str,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    mcp_manager: Optional["MCPManager"] = None
) -> str:
    """
    Single model chat with full tool calling support.
    Uses MODEL_CATALOG for connectivity, MODEL_REGISTRY for system prompts (optional).
    """
    # Check MODEL_CATALOG for connectivity info
    if model_name not in MODEL_CATALOG:
        return f"Model {model_name} not in catalog. Run /models refresh or manually add with /models add."
    
    catalog_entry = MODEL_CATALOG[model_name]
    
    # Resolve API credentials
    base_url = catalog_entry["base_url"]
    api_key_env = catalog_entry["api_key_env"]
    endpoint_type = catalog_entry["endpoint_type"]
    
    api_key = config.get_env_key(api_key_env) if api_key_env else None
    
    if endpoint_type != "local" and not api_key:
        return f"Missing API key for {model_name}. Set {api_key_env} environment variable or use /key."
    
    # Get system prompt from MODEL_REGISTRY if available, else use fallback
    if model_name in MODEL_REGISTRY:
        system_prompt = MODEL_REGISTRY[model_name]["system_prompt"]
    else:
        system_prompt = "You are a helpful AI assistant in RED SHINOBI."
    
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]
    
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    
    messages.append({"role": "user", "content": prompt})
    
    try:
        api_client = AsyncOpenAI(base_url=base_url, api_key=api_key or "")
        
        tools = await get_mcp_tools_for_llm(mcp_manager)
        
        # ===== DEBUG WIRETAP =====
        rprint(f"[bold yellow]DEBUG: Passing {len(tools) if tools else 0} tools to {model_name}[/bold yellow]")
        
        api_kwargs: Dict[str, Any] = {
            "model": model_name,  # Use the catalog model_id directly
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS
        }
        
        if tools:
            api_kwargs["tools"] = tools
            api_kwargs["tool_choice"] = "auto"
        
        response = await api_client.chat.completions.create(**api_kwargs)
        assistant_msg = response.choices[0].message
        
        tool_round = 0
        while assistant_msg.tool_calls and tool_round < MAX_TOOL_ROUNDS:
            tool_round += 1
            console.print(f"[cyan]⚙️ {model_name} calling tools (round {tool_round})...[/cyan]")
            
            tool_call_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": assistant_msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in assistant_msg.tool_calls
                ]
            }
            messages.append(tool_call_msg)
            
            for tc in assistant_msg.tool_calls:
                fn_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                
                if "__" in fn_name:
                    server_name, tool_name = fn_name.split("__", 1)
                else:
                    server_name, tool_name = "", fn_name
                
                console.print(f"[dim]  → {server_name}/{tool_name}[/dim]")
                
                if mcp_manager and server_name:
                    result = await mcp_manager.call_tool(server_name, tool_name, args)
                    content = extract_tool_result(result)
                else:
                    content = f"Error: Cannot execute {fn_name}"
                
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
                console.print(f"[dim]  ✓ Done[/dim]")
            
            followup_kwargs: Dict[str, Any] = {
                "model": model_info["api_model_id"],
                "messages": messages,
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS
            }
            if tools:
                followup_kwargs["tools"] = tools
                followup_kwargs["tool_choice"] = "auto"
            
            followup = await api_client.chat.completions.create(**followup_kwargs)
            assistant_msg = followup.choices[0].message
        
        return assistant_msg.content if assistant_msg.content else f"{model_name}: Done."
        
    except RateLimitError:
        return f"{model_name}: Rate limit hit."
    except APIError as e:
        return f"{model_name}: API error - {type(e).__name__}"
    except Exception as e:
        return f"{model_name}: Error - {e}"


# =============================================================================
# RUN AGENT CONVERSATION - Strict 1-on-1 with Single Handoff
# =============================================================================

async def run_agent_conversation(
    task: str,
    active_models: Optional[List[str]] = None,
    mode: str = "offline",
    max_turns: int = 2,
    mcp_manager: Optional["MCPManager"] = None
) -> List[Dict[str, Any]]:
    """
    Strict 1-on-1 conversation with optional single handoff.
    
    Rules:
    1. First responder = active_models[0] unless user @mentions a valid model.
    2. After response, if AI @mentions another valid model, do ONE handoff and stop.
    3. No loops. No group chat. Maximum 2 responses total.
    
    Args:
        task: User's message/task
        active_models: List of models (CLI sends [current_model], UI can send multiple)
        mode: "offline" or "online"
        max_turns: Maximum responses (default 2 for handoff)
        mcp_manager: MCP manager for tool calling
    
    Returns:
        List of conversation messages with role, content, model keys
    """
    conversation: List[Dict[str, Any]] = []
    
    if not active_models or len(active_models) == 0:
        return [{
            "role": "assistant",
            "content": "No model selected. Set API key with /key, then run /models refresh and /model <id>.",
            "model": "system"
        }]
    
    
    user_mentioned = extract_mentioned_model(task)
    if user_mentioned:
        first_model = user_mentioned
        console.print(f"[dim]Routing to @{first_model}[/dim]")
    else:
        first_model = active_models[0]
        console.print(f"[dim]Using: {first_model}[/dim]")
    
    response1 = await chat_worker(
        model_name=first_model,
        prompt=task,
        chat_history=None,
        mcp_manager=mcp_manager
    )
    
    conversation.append({
        "role": "assistant",
        "content": response1,
        "model": first_model
    })
    
    handoff_model = extract_mentioned_model(response1)
    
    if handoff_model and handoff_model != first_model:
        console.print(f"[dim]{first_model} hands off to @{handoff_model}[/dim]")
        
        handoff_prompt = f"{first_model} said:\n\n{response1}\n\nPlease respond."
        
        response2 = await chat_worker(
            model_name=handoff_model,
            prompt=handoff_prompt,
            chat_history=conversation,
            mcp_manager=mcp_manager
        )
        
        conversation.append({
            "role": "assistant",
            "content": response2,
            "model": handoff_model
        })
    
    return conversation

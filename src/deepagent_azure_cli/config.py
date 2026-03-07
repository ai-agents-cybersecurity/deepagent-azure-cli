"""
Configuration management for DeepAgent Azure CLI.

Supports configuration via:
  1. Environment variables (highest priority)
  2. .env file in current directory
  3. ~/.deepagent-azure/config.env (user-level defaults)
  4. Built-in defaults (lowest priority)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
USER_CONFIG_DIR = Path.home() / ".deepagent-azure"
USER_CONFIG_FILE = USER_CONFIG_DIR / "config.env"
LOCAL_ENV_FILE = Path(".env")


def _load_env_files() -> None:
    """Load .env files in priority order (local overrides user-level)."""
    if USER_CONFIG_FILE.exists():
        load_dotenv(USER_CONFIG_FILE, override=False)
    if LOCAL_ENV_FILE.exists():
        load_dotenv(LOCAL_ENV_FILE, override=True)


def _extract_base_endpoint(endpoint: str) -> str:
    """
    Extract the base URL from a full Azure OpenAI endpoint.

    Handles cases where the user provides a full URL like:
      https://my-resource.openai.azure.com/openai/responses?api-version=2025-04-01-preview

    Returns just:
      https://my-resource.openai.azure.com
    """
    if not endpoint:
        return endpoint

    parsed = urlparse(endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return base


def _extract_api_version_from_endpoint(endpoint: str) -> Optional[str]:
    """
    Extract api-version from the endpoint query string, if present.

    E.g. from ?api-version=2025-04-01-preview returns "2025-04-01-preview"
    """
    if not endpoint:
        return None

    parsed = urlparse(endpoint)
    params = parse_qs(parsed.query)
    versions = params.get("api-version", [])
    return versions[0] if versions else None


def _getenv_first(*var_names: str, default: str = "") -> str:
    """Return the first non-empty environment variable from the given names."""
    for name in var_names:
        val = os.getenv(name, "")
        if val:
            return val
    return default


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------
@dataclass
class AzureConfig:
    """Azure OpenAI connection settings."""

    api_key: str = ""
    endpoint: str = ""  # Base URL, e.g. https://my-resource.openai.azure.com
    deployment_name: str = ""  # e.g. gpt-5.3-codex
    api_version: str = "2024-08-01-preview"

    # Model identifier used by langchain (provider:model format)
    model_string: str = ""

    # Store the original endpoint (before parsing) for display purposes
    raw_endpoint: str = ""

    def validate(self) -> list[str]:
        """Return a list of missing required fields."""
        missing = []
        if not self.api_key:
            missing.append("AZURE_OPENAI_API_KEY")
        if not self.endpoint:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if not self.deployment_name:
            missing.append(
                "AZURE_OPENAI_DEPLOYMENT_NAME (or AZURE_OPENAT_DEPLOYMENT / AZURE_OPENAI_DEPLOYMENT)"
            )
        return missing


@dataclass
class AgentConfig:
    """Agent behaviour settings."""

    # System prompt override (None = use DeepAgents default)
    system_prompt: Optional[str] = None

    # Working directory for file operations
    root_dir: str = "."

    # Human-in-the-loop: require approval for shell + writes
    approve_shell: bool = True
    approve_writes: bool = True

    # Auto-approve read-only operations
    approve_reads: bool = False

    # LLM reasoning effort (low|medium|high)
    reasoning_effort: str = "medium"

    # Max retries for LLM calls (handles 429 / 5xx)
    max_retries: int = 6

    # Timeout per LLM call in seconds
    timeout: int = 120

    # Enable web search tool (requires TAVILY_API_KEY)
    enable_search: bool = False

    # SQLite checkpoint path (None = in-memory)
    checkpoint_db: Optional[str] = None

    # Agent name (used for memory directory)
    agent_name: str = "deepagent-azure"


@dataclass
class AppConfig:
    """Top-level application configuration."""

    azure: AzureConfig = field(default_factory=AzureConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)


# ---------------------------------------------------------------------------
# Load configuration from environment
# ---------------------------------------------------------------------------
def load_config() -> AppConfig:
    """Build an AppConfig from environment variables and .env files."""
    _load_env_files()

    # Read the raw endpoint - might contain full path + query params
    raw_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")

    # Extract base URL (strip /openai/responses?api-version=... etc.)
    base_endpoint = _extract_base_endpoint(raw_endpoint)

    # Try to extract api-version from the URL query string first,
    # then fall back to explicit env vars, then to default
    api_version_from_url = _extract_api_version_from_endpoint(raw_endpoint)
    api_version = _getenv_first(
        "OPENAI_API_VERSION",
        "AZURE_OPENAI_API_VERSION",
        default=api_version_from_url or "2025-04-01-preview",
    )

    # Be forgiving: teams copy/paste env names, and typos happen in real life.
    deployment_name = _getenv_first(
        "AZURE_OPENAI_DEPLOYMENT_NAME",  # standard
        "AZURE_OPENAI_DEPLOYMENT",       # alternate standard
        "AZURE_OPENAT_DEPLOYMENT",       # common typo - support it
    )

    azure = AzureConfig(
        api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
        endpoint=base_endpoint,
        deployment_name=deployment_name,
        api_version=api_version,
        model_string=os.getenv("DEEPAGENT_MODEL", ""),
        raw_endpoint=raw_endpoint,
    )

    agent = AgentConfig(
        system_prompt=os.getenv("DEEPAGENT_SYSTEM_PROMPT"),
        root_dir=os.getenv("DEEPAGENT_ROOT_DIR", "."),
        approve_shell=os.getenv("DEEPAGENT_APPROVE_SHELL", "true").lower() == "true",
        approve_writes=os.getenv("DEEPAGENT_APPROVE_WRITES", "true").lower() == "true",
        approve_reads=os.getenv("DEEPAGENT_APPROVE_READS", "false").lower() == "true",
        reasoning_effort=os.getenv("DEEPAGENT_REASONING_EFFORT", "medium"),
        max_retries=int(os.getenv("DEEPAGENT_MAX_RETRIES", "6")),
        timeout=int(os.getenv("DEEPAGENT_TIMEOUT", "120")),
        enable_search=os.getenv("DEEPAGENT_ENABLE_SEARCH", "false").lower() == "true",
        checkpoint_db=os.getenv("DEEPAGENT_CHECKPOINT_DB"),
        agent_name=os.getenv("DEEPAGENT_NAME", "deepagent-azure"),
    )

    return AppConfig(azure=azure, agent=agent)


# ---------------------------------------------------------------------------
# Bootstrap: create user config directory + template
# ---------------------------------------------------------------------------
def init_user_config() -> Path:
    """Create ~/.deepagent-azure/config.env with a template if it doesn't exist."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not USER_CONFIG_FILE.exists():
        USER_CONFIG_FILE.write_text(
            """\
# ============================================================
# DeepAgent Azure CLI - Configuration
# ============================================================
# Copy this file to your project directory as .env, or keep it
# here as user-level defaults.
#
# Required: Azure OpenAI connection
# ============================================================
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-codex
AZURE_OPENAI_API_VERSION=2025-04-01-preview

# Note: AZURE_OPENAI_ENDPOINT can be either:
#   - Base URL:  https://my-resource.openai.azure.com
#   - Full URL:  https://my-resource.openai.azure.com/openai/responses?api-version=2025-04-01-preview
# The CLI will automatically extract the base URL and api-version.
#
# Note: The deployment name env var supports multiple names:
#   AZURE_OPENAI_DEPLOYMENT_NAME, AZURE_OPENAI_DEPLOYMENT, or AZURE_OPENAT_DEPLOYMENT

# ============================================================
# Optional: Agent behaviour
# ============================================================
# DEEPAGENT_APPROVE_SHELL=true
# DEEPAGENT_APPROVE_WRITES=true
# DEEPAGENT_REASONING_EFFORT=medium
# DEEPAGENT_ROOT_DIR=.
# DEEPAGENT_MAX_RETRIES=6
# DEEPAGENT_TIMEOUT=120
# DEEPAGENT_CHECKPOINT_DB=~/.deepagent-azure/sessions.db

# ============================================================
# Optional: Web search (requires tavily-python)
# ============================================================
# DEEPAGENT_ENABLE_SEARCH=false
# TAVILY_API_KEY=

# ============================================================
# Optional: Override model string (advanced)
# ============================================================
# DEEPAGENT_MODEL=azure_openai:gpt-5.3-codex
"""
        )

    return USER_CONFIG_FILE

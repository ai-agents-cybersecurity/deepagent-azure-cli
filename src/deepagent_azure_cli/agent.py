"""
Core agent factory — wires DeepAgents to Azure OpenAI.

Creates a fully configured coding assistant agent with:
  - Azure OpenAI as the LLM backend
  - LocalShellBackend for filesystem + shell access
  - Human-in-the-loop approval for shell commands and file writes
  - SQLite checkpointing for session persistence
  - Optional web search tool
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from langchain_openai import AzureChatOpenAI

from .config import AppConfig


def _build_model(config: AppConfig) -> AzureChatOpenAI:
    """Construct the AzureChatOpenAI model instance."""
    azure = config.azure

    return AzureChatOpenAI(
        azure_deployment=azure.deployment_name,
        azure_endpoint=azure.endpoint,
        api_key=azure.api_key,
        api_version=azure.api_version,
        max_retries=config.agent.max_retries,
        timeout=config.agent.timeout,
    )


def _build_interrupt_config(config: AppConfig) -> dict[str, Any]:
    """Build the interrupt_on mapping for human-in-the-loop."""
    interrupts: dict[str, Any] = {}

    if config.agent.approve_shell:
        interrupts["execute"] = True  # bash / shell execution
    if config.agent.approve_writes:
        interrupts["write_file"] = True
        interrupts["edit_file"] = True
    if config.agent.approve_reads:
        interrupts["read_file"] = True

    return interrupts


def _build_extra_tools(config: AppConfig) -> list:
    """Build optional additional tools (e.g., web search)."""
    tools = []

    if config.agent.enable_search:
        try:
            from tavily import TavilyClient

            tavily_api_key = os.getenv("TAVILY_API_KEY", "")
            if tavily_api_key:
                client = TavilyClient(api_key=tavily_api_key)

                def web_search(
                    query: str,
                    max_results: int = 5,
                ) -> str:
                    """Search the web for current information.

                    Args:
                        query: The search query.
                        max_results: Maximum number of results to return.
                    """
                    results = client.search(query, max_results=max_results)
                    formatted = []
                    for r in results.get("results", []):
                        formatted.append(
                            f"**{r.get('title', 'No title')}**\n"
                            f"{r.get('url', '')}\n"
                            f"{r.get('content', '')}\n"
                        )
                    return "\n---\n".join(formatted) if formatted else "No results found."

                tools.append(web_search)
        except ImportError:
            pass  # tavily not installed, skip silently

    return tools


def _build_checkpointer(config: AppConfig):
    """Build a checkpointer for session persistence."""
    db_path = config.agent.checkpoint_db

    if db_path:
        db_path = os.path.expanduser(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver

            return SqliteSaver.from_conn_string(db_path)
        except ImportError:
            pass

    # Fallback: in-memory checkpointer (sessions don't survive restart)
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def create_agent(
    config: AppConfig,
    extra_tools: Optional[list] = None,
    system_prompt_override: Optional[str] = None,
):
    """
    Create and return a fully configured DeepAgent wired to Azure OpenAI.

    Returns a compiled LangGraph graph that can be invoked or streamed.
    """
    from deepagents import create_deep_agent
    from deepagents.backends import LocalShellBackend

    model = _build_model(config)
    tools = _build_extra_tools(config)
    if extra_tools:
        tools.extend(extra_tools)

    interrupt_config = _build_interrupt_config(config)
    checkpointer = _build_checkpointer(config)

    # Resolve the working directory
    root_dir = os.path.abspath(os.path.expanduser(config.agent.root_dir))

    # System prompt
    prompt = system_prompt_override or config.agent.system_prompt

    # Build the agent
    agent = create_deep_agent(
        name=config.agent.agent_name,
        model=model,
        tools=tools if tools else None,
        system_prompt=prompt,
        backend=LocalShellBackend(root_dir=root_dir),
        interrupt_on=interrupt_config if interrupt_config else None,
        checkpointer=checkpointer,
    )

    return agent

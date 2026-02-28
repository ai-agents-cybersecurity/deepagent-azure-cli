"""
CLI entry point for DeepAgent Azure CLI.

Usage:
    deepagent-azure                     # Interactive REPL
    deepagent-azure --init              # Create config template
    deepagent-azure -m "fix the tests"  # One-shot mode
    deepagent-azure --root-dir ./myproj # Override working directory
    daz                                 # Short alias
"""

from __future__ import annotations

import sys

import click
from rich.console import Console

from .config import AppConfig, init_user_config, load_config

console = Console()


def _validate_config(config: AppConfig) -> bool:
    """Validate configuration and print helpful errors."""
    missing = config.azure.validate()
    if missing:
        console.print("[bold red]Missing required configuration:[/bold red]\n")
        for var in missing:
            console.print(f"  [red]- {var}[/red]")
        console.print(
            "\n[dim]Set these as environment variables, in a .env file, "
            "or run [bold]deepagent-azure --init[/bold] to create a config template.[/dim]"
        )
        return False
    return True


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--init",
    is_flag=True,
    default=False,
    help="Create a config template at ~/.deepagent-azure/config.env",
)
@click.option(
    "-m",
    "--message",
    default=None,
    help="One-shot mode: send a single message and exit.",
)
@click.option(
    "--root-dir",
    default=None,
    help="Working directory for file operations (default: current dir).",
)
@click.option(
    "--no-approve",
    is_flag=True,
    default=False,
    help="Disable human-in-the-loop approval (YOLO mode).",
)
@click.option(
    "--search",
    is_flag=True,
    default=False,
    help="Enable web search tool (requires TAVILY_API_KEY).",
)
@click.option(
    "--checkpoint-db",
    default=None,
    help="Path to SQLite DB for session persistence.",
)
@click.option(
    "--deployment",
    default=None,
    help="Override Azure OpenAI deployment name.",
)
@click.option(
    "--endpoint",
    default=None,
    help="Override Azure OpenAI endpoint URL.",
)
def main(
    init: bool,
    message: str | None,
    root_dir: str | None,
    no_approve: bool,
    search: bool,
    checkpoint_db: str | None,
    deployment: str | None,
    endpoint: str | None,
) -> None:
    """DeepAgent Azure CLI — a coding assistant powered by DeepAgents + Azure OpenAI."""

    # --init: create config template and exit
    if init:
        path = init_user_config()
        console.print(f"[green]Config template created at:[/green] {path}")
        console.print("[dim]Edit the file and fill in your Azure OpenAI credentials.[/dim]")
        return

    # Load configuration
    config = load_config()

    # Apply CLI overrides
    if root_dir:
        config.agent.root_dir = root_dir
    if no_approve:
        config.agent.approve_shell = False
        config.agent.approve_writes = False
    if search:
        config.agent.enable_search = True
    if checkpoint_db:
        config.agent.checkpoint_db = checkpoint_db
    if deployment:
        config.azure.deployment_name = deployment
    if endpoint:
        config.azure.endpoint = endpoint

    # Validate
    if not _validate_config(config):
        sys.exit(1)

    # Import agent factory (deferred to keep startup fast)
    from .agent import create_agent

    try:
        agent = create_agent(config)
    except Exception as e:
        console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
        console.print(
            "\n[dim]Check your Azure OpenAI credentials and deployment name.\n"
            "Run with --init to create a config template.[/dim]"
        )
        sys.exit(1)

    # One-shot mode
    if message:
        _run_oneshot(agent, config, message)
        return

    # Interactive REPL
    from .repl import AgentREPL

    repl = AgentREPL(agent, config)
    repl.run()


def _run_oneshot(agent, config: AppConfig, message: str) -> None:
    """Execute a single message and print the result."""
    import uuid

    thread_id = str(uuid.uuid4())

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}},
        )

        # Print the final AI message
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "ai" and msg.content:
                console.print(msg.content)
                break

    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

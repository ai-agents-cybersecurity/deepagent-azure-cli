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
from .interaction_logger import DailyInteractionLogger, extract_token_usage, merge_token_usage

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
@click.option(
    "--effort",
    type=click.Choice(["low", "medium", "high"], case_sensitive=False),
    default=None,
    help="LLM reasoning effort (low|medium|high). Overrides DEEPAGENT_REASONING_EFFORT.",
)
@click.option(
    "--effort-low",
    is_flag=True,
    default=False,
    help="Shortcut for --effort low.",
)
@click.option(
    "--effort-medium",
    is_flag=True,
    default=False,
    help="Shortcut for --effort medium.",
)
@click.option(
    "--effort-high",
    is_flag=True,
    default=False,
    help="Shortcut for --effort high.",
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
    effort: str | None,
    effort_low: bool,
    effort_medium: bool,
    effort_high: bool,
) -> None:
    """DeepAgent Azure CLI — a coding assistant powered by DeepAgents + Azure OpenAI."""

    # --init: create config template and exit
    if init:
        path = init_user_config()
        console.print(f"[green]Config template created at:[/green] {path}")
        console.print("[dim]Edit the file and fill in your Azure OpenAI credentials.[/dim]")
        return

    # Load config once, then layer CLI flags on top (easier to reason about precedence).
    config = load_config()

    # Default root dir to the directory where 'daz' is invoked from.
    # This makes relative file references (e.g. 'review src.py') work naturally.
    if not root_dir and (not config.agent.root_dir or config.agent.root_dir == "."):
        config.agent.root_dir = "."

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

    # Priority order is intentional: explicit shortcut flags win over the generic --effort switch.
    if effort_low:
        config.agent.reasoning_effort = "low"
    elif effort_medium:
        config.agent.reasoning_effort = "medium"
    elif effort_high:
        config.agent.reasoning_effort = "high"
    elif effort:
        config.agent.reasoning_effort = effort.lower()

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

    # Interactive REPL (now Textual TUI)
    from .repl import AgentREPL

    repl = AgentREPL(agent, config)
    repl.run()


def _run_oneshot(agent, config: AppConfig, message: str) -> None:
    """Execute a single message and print the result."""
    import uuid

    thread_id = str(uuid.uuid4())
    logger = DailyInteractionLogger()
    turn_id = logger.new_turn_id()

    logger.log_request(thread_id=thread_id, turn_id=turn_id, message=message)
    logger.flush()

    token_totals: dict[str, int | None] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}},
        )

        # Extract token usage from result messages
        messages = result.get("messages", [])
        for msg in messages:
            usage = extract_token_usage(msg)
            if usage is not None:
                token_totals = merge_token_usage(token_totals, usage)

        # Print the final AI message
        content = None
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "ai" and msg.content:
                content = msg.content
                if content:
                    console.print(content)
                    break

        logger.log_completion(
            thread_id=thread_id,
            turn_id=turn_id,
            status="completed",
            token_usage={
                "input_tokens": token_totals.get("input_tokens") or 0,
                "output_tokens": token_totals.get("output_tokens") or 0,
                "total_tokens": token_totals.get("total_tokens") or 0,
            },
        )
        logger.flush(force=True)

    except KeyboardInterrupt:
        logger.log_completion(
            thread_id=thread_id,
            turn_id=turn_id,
            status="interrupted",
            error="KeyboardInterrupt",
        )
        logger.flush(force=True)
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(130)
    except Exception as e:
        logger.log_completion(
            thread_id=thread_id,
            turn_id=turn_id,
            status="error",
            error=str(e),
        )
        logger.flush(force=True)
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

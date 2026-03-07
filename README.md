# DeepAgent Azure CLI

![Version](https://img.shields.io/badge/version-0.2.0-brightgreen) ![Release](https://img.shields.io/badge/release-March%202026-blue) ![License](https://img.shields.io/badge/License-MIT-blue.svg) ![Python](https://img.shields.io/badge/python-3.11+-blue) ![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-green) ![API](https://img.shields.io/badge/API-Azure%20OpenAI-0078D4?logo=microsoftazure) ![Framework](https://img.shields.io/badge/Framework-LangGraph%20%2B%20DeepAgents-orange) ![Built with](https://img.shields.io/badge/Built%20with-Claude-7B3F00?logo=anthropic) ![Author](https://img.shields.io/badge/Author-Nicolas%20Cravino-lightgrey?logo=github)

[![Apple Books](https://img.shields.io/badge/Apple_Books-AI_Agents_in_Cybersecurity-FA5B30?style=for-the-badge&logo=apple&logoColor=white)](https://books.apple.com/us/book/ai-agents-in-cybersecurity/id6751737181)

A turnkey coding assistant CLI powered by [LangChain DeepAgents](https://github.com/langchain-ai/deepagents) and **Azure OpenAI**.

Think Claude Code or OpenAI Codex CLI — but wired to your Azure OpenAI deployment, fully open source, and extensible with custom tools.

## What You Get

- **Full coding agent**: file read/write/edit, shell execution, glob, grep, planning, sub-agents
- **Azure OpenAI native**: connects directly to your Azure OpenAI deployment (GPT-4, GPT-5.3-Codex, etc.)
- **Textual TUI**: modern terminal UI with scrollable timeline, streaming updates, and inline approval prompts
- **Reasoning effort control**: tune LLM reasoning depth via `--effort low|medium|high` (or shortcut flags)
- **Human-in-the-loop**: approves shell commands and file writes before execution
- **Session persistence**: resume conversations across restarts (SQLite checkpoint)
- **Interaction logging**: daily JSONL logs with token usage tracking (`~/.deepagent-azure/logs/`)
- **`/init` command**: auto-generates a comprehensive `agents.md` project knowledge file with reflection review
- **Extensible**: add custom tools (JIRA, CI/CD, internal APIs) with a simple decorator
- **Zero binaries**: pure Python, installs from PyPI or clones from git

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/ai-agents-cybersecurity/deepagent-azure-cli.git
cd deepagent-azure-cli
pip install -e .
```

Or install directly:

```bash
pip install git+https://github.com/ai-agents-cybersecurity/deepagent-azure-cli.git
```

### 2. Configure

```bash
# Option A: environment variables
export AZURE_OPENAI_API_KEY="your-key"
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT_NAME="gpt-5.3-codex"

# Option B: create a config template
deepagent-azure --init
# Then edit ~/.deepagent-azure/config.env

# Option C: use a .env file in your project directory
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run

```bash
# Interactive TUI
deepagent-azure

# Short alias
daz

# One-shot mode
daz -m "find all TODO comments in this project and create a summary"

# Override working directory
daz --root-dir ./my-project

# YOLO mode (no approval prompts)
daz --no-approve

# Control reasoning effort
daz --effort high
daz --effort-low     # shortcut flags
daz --effort-medium
daz --effort-high
```

## Configuration

All settings can be set via environment variables, a `.env` file, or CLI flags.

| Environment Variable | CLI Flag | Default | Description |
|---|---|---|---|
| `AZURE_OPENAI_API_KEY` | — | *required* | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | `--endpoint` | *required* | Azure OpenAI endpoint URL (base or full — auto-parsed) |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | `--deployment` | *required* | Model deployment name (also reads `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAT_DEPLOYMENT`) |
| `AZURE_OPENAI_API_VERSION` | — | `2025-04-01-preview` | API version (also reads `OPENAI_API_VERSION`, or extracted from endpoint URL) |
| `DEEPAGENT_REASONING_EFFORT` | `--effort` | `medium` | LLM reasoning effort: `low`, `medium`, or `high` |
| `DEEPAGENT_APPROVE_SHELL` | `--no-approve` | `true` | Require approval for shell commands |
| `DEEPAGENT_APPROVE_WRITES` | `--no-approve` | `true` | Require approval for file writes |
| `DEEPAGENT_ROOT_DIR` | `--root-dir` | `.` | Working directory |
| `DEEPAGENT_CHECKPOINT_DB` | `--checkpoint-db` | in-memory | SQLite path for session persistence |
| `DEEPAGENT_ENABLE_SEARCH` | `--search` | `false` | Enable web search (needs `TAVILY_API_KEY`) |
| `DEEPAGENT_MAX_RETRIES` | — | `6` | Max retries for LLM calls |
| `DEEPAGENT_TIMEOUT` | — | `120` | Timeout per LLM call (seconds) |

### Smart endpoint parsing

The CLI automatically handles both base URLs and full Azure OpenAI URLs:

```bash
# Both of these work — the CLI extracts the base URL and api-version automatically:
AZURE_OPENAI_ENDPOINT=https://my-resource.openai.azure.com
AZURE_OPENAI_ENDPOINT=https://my-resource.openai.azure.com/openai/responses?api-version=2025-04-01-preview
```

## TUI Commands

| Command | Description |
|---|---|
| `/new` | Start a new session |
| `/init` | Build/update `agents.md` project knowledge file (high-effort + reflection) |
| `/config` | Show current configuration |
| `/help` | Show available commands |
| `/quit` | Exit |

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+C` | Quit |
| `Ctrl+L` | Copy last assistant response to clipboard |
| `Ctrl+T` | Copy full timeline to clipboard |

## Adding Custom Tools

Extend the agent with your own tools for internal APIs, databases, CI/CD, etc.:

```python
from langchain_core.tools import tool
from deepagent_azure_cli.agent import create_agent
from deepagent_azure_cli.config import load_config

@tool
def query_jira(project_key: str, status: str = "Open") -> str:
    """Query JIRA for issues in a project."""
    # Your JIRA API call here
    ...

config = load_config()
agent = create_agent(config, extra_tools=[query_jira])
```

See `examples/` for more.

## Using as a Library

```python
from deepagent_azure_cli.agent import create_agent
from deepagent_azure_cli.config import load_config

config = load_config()
agent = create_agent(config)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Refactor the auth module to use JWT"}]},
    config={"configurable": {"thread_id": "my-session"}},
)
```

## Project Structure

```
deepagent-azure-cli/
├── src/deepagent_azure_cli/
│   ├── __init__.py              # Package metadata
│   ├── cli.py                   # CLI entry point (click)
│   ├── config.py                # Configuration management
│   ├── agent.py                 # Agent factory (DeepAgents + Azure OpenAI)
│   ├── repl.py                  # Compatibility shim → delegates to TUI
│   ├── interaction_logger.py    # Daily JSONL interaction & token logger
│   └── tui/
│       ├── __init__.py
│       ├── app.py               # Main Textual TUI application
│       ├── events.py            # UI event types (decoupled from LangGraph)
│       ├── hitl.py              # Human-in-the-loop interrupt handling
│       ├── renderer.py          # Human-friendly rendering helpers
│       └── widgets.py           # Timeline, ApprovalDock widgets
├── examples/
│   ├── basic_usage.py           # Programmatic usage
│   └── custom_tools.py          # Adding custom tools
├── .env.example                 # Config template
├── pyproject.toml               # Package definition
├── LICENSE                      # MIT
└── README.md
```

## Behind the Scenes

This project is a thin, opinionated wrapper around:

- **[DeepAgents](https://github.com/langchain-ai/deepagents)** — the agent framework (planning, file ops, shell, sub-agents)
- **[LangChain](https://github.com/langchain-ai/langchain)** — LLM abstraction and tool framework
- **[LangGraph](https://github.com/langchain-ai/langgraph)** — stateful agent orchestration with checkpointing
- **[AzureChatOpenAI](https://python.langchain.com/docs/integrations/chat/azure_chat_openai/)** — Azure OpenAI integration
- **[Textual](https://github.com/Textualize/textual)** — modern terminal user interface framework

The agent gets all of DeepAgents' built-in capabilities for free: `write_todos`, `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`, `execute` (shell), `task` (sub-agents), plus whatever custom tools you add.

## What's New in v0.2.0

- **Textual TUI**: replaced the Rich-only REPL with a full Textual terminal UI featuring a scrollable timeline, streaming output, and inline Approve/Reject buttons for human-in-the-loop prompts.
- **Reasoning effort control**: new `--effort low|medium|high` flag (plus `--effort-low`, `--effort-medium`, `--effort-high` shortcuts) and the `DEEPAGENT_REASONING_EFFORT` environment variable let you tune LLM reasoning depth per invocation.
- **`/init` command**: bootstraps (or updates) an `agents.md` project knowledge file at the repository root, using high-effort reasoning and an automatic reflection sub-agent review pass.
- **Interaction logging**: every request/completion is logged to daily JSONL files in `~/.deepagent-azure/logs/` with token-usage tracking, making cost attribution and debugging straightforward.
- **Working directory hint**: when no custom system prompt is set, the agent now receives an explicit root-dir context line so relative paths resolve predictably.
- **Improved HITL payloads**: the interrupt handler now supports the `action_requests` interrupt schema for richer approval metadata.
- **Clipboard shortcuts**: `Ctrl+L` copies the last assistant response; `Ctrl+T` copies the full timeline.

## Corporate Proxy Setup

If you're behind a corporate proxy:

```bash
# For pip
pip install -e . --proxy http://user:pass@proxy:port

# For the Azure OpenAI SDK (uses HTTPS_PROXY)
export HTTPS_PROXY=http://user:pass@proxy:port

# If your proxy uses a custom CA cert
export REQUESTS_CA_BUNDLE=/path/to/corporate-ca.crt
```

## License

MIT

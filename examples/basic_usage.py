"""
Example: Using DeepAgent Azure CLI programmatically.

This shows how to use the agent as a library rather than via the CLI.
"""

import os

from deepagent_azure_cli.agent import create_agent
from deepagent_azure_cli.config import AppConfig, AgentConfig, AzureConfig


def main():
    # Configure directly in code (or use load_config() for env vars)
    config = AppConfig(
        azure=AzureConfig(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
            api_version="2024-08-01-preview",
        ),
        agent=AgentConfig(
            root_dir=".",
            approve_shell=True,
            approve_writes=True,
        ),
    )

    # Create the agent
    agent = create_agent(config)

    # Invoke with a task
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "List all Python files in this directory and summarize what each does."}]},
        config={"configurable": {"thread_id": "example-session-1"}},
    )

    # Print the final response
    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content:
            print(msg.content)
            break


if __name__ == "__main__":
    main()

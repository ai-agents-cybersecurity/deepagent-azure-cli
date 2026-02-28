"""
Example: Adding custom tools to the agent.

This shows how to extend the agent with your own tools —
e.g., a tool that queries your company's internal API,
runs database queries, or interacts with your CI/CD pipeline.
"""

import os
from langchain_core.tools import tool

from deepagent_azure_cli.agent import create_agent
from deepagent_azure_cli.config import load_config


# Define custom tools using the @tool decorator
@tool
def query_jira(project_key: str, status: str = "Open") -> str:
    """Query JIRA for issues in a project.

    Args:
        project_key: The JIRA project key (e.g., 'PROJ').
        status: Filter by status (default: 'Open').
    """
    # Replace with your actual JIRA API call
    return f"[Mock] Found 3 {status} issues in {project_key}: PROJ-101, PROJ-102, PROJ-103"


@tool
def run_pipeline(branch: str = "main") -> str:
    """Trigger a CI/CD pipeline run.

    Args:
        branch: The branch to build (default: 'main').
    """
    # Replace with your actual CI/CD API call
    return f"[Mock] Pipeline triggered for branch '{branch}'. Build #456 started."


@tool
def query_internal_docs(query: str) -> str:
    """Search the company's internal documentation.

    Args:
        query: The search query.
    """
    # Replace with your actual search API (Confluence, SharePoint, etc.)
    return f"[Mock] Found 5 results for '{query}' in internal docs."


def main():
    config = load_config()

    # Pass custom tools when creating the agent
    agent = create_agent(
        config,
        extra_tools=[query_jira, run_pipeline, query_internal_docs],
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Check JIRA for open bugs in the BACKEND project and summarize them."}]},
        config={"configurable": {"thread_id": "custom-tools-demo"}},
    )

    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content:
            print(msg.content)
            break


if __name__ == "__main__":
    main()

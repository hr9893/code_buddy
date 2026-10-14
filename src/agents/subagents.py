from collections.abc import Callable

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
)
from langsmith import traceable

from src.config.llm import get_model
from src.config.system_prompts import (
    REPO_EXPLORER_PROMPT,
    CODER_PROMPT,
    PR_PROMPT,
)
from src.github.tool_sets import (
    get_repo_explorer_tools,
    get_coder_tools,
    get_pr_agent_tools,
)
from src.agents.tracing import trace_tool_calls


@traceable(name="create_repo_explorer_agent", run_type="chain")
def create_repo_explorer_agent():
    """Investigates the repository without modifying code."""
    return create_deep_agent(
        model=get_model(),
        tools=get_repo_explorer_tools(),
        system_prompt=REPO_EXPLORER_PROMPT,
        middleware=[
            trace_tool_calls("repo-explorer"),
        ],
    )


@traceable(name="create_coder_agent", run_type="chain")
def create_coder_agent(
    issue_number: int | None = None,
    on_pull_request_created: Callable[[str], None] | None = None,
):
    """Implements code changes and opens a pull request."""
    return create_deep_agent(
        model=get_model(),
        tools=get_coder_tools(issue_number),
        system_prompt=CODER_PROMPT.replace(
            "{issue_number}", str(issue_number or "manual")
        ),
        middleware=[
            trace_tool_calls("coder", on_pull_request_created),
        ],
    )


@traceable(name="create_pr_agent", run_type="chain")
def create_pr_agent(
    issue_number: int | None = None,
    on_pull_request_created: Callable[[str], None] | None = None,
):
    """Manages Git branches, commits, and pull requests."""
    return create_deep_agent(
        model=get_model(),
        tools=get_pr_agent_tools(),
        system_prompt=PR_PROMPT.replace(
            "{issue_number}", str(issue_number or "manual")
        ),
        middleware=[
            trace_tool_calls("pr-agent", on_pull_request_created),
        ],
    )

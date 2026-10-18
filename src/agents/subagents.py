from collections.abc import Callable

from deepagents import create_deep_agent
from langsmith import traceable

from src.agents.tracing import trace_tool_calls
from src.config.llm import get_model
from src.config.system_prompts import CODER_PROMPT, PR_PROMPT, REPO_EXPLORER_PROMPT
from src.github.tool_sets import (
    get_coder_tools,
    get_pr_agent_tools,
    get_repo_explorer_tools,
)
from src.skills.skill_loader import load_skill


@traceable(name="create_repo_explorer_agent", run_type="chain")
def create_repo_explorer_agent(effort: str = "moderate"):
    """Investigates the repository without modifying code."""
    return create_deep_agent(
        model=get_model("fast"),
        tools=get_repo_explorer_tools(),
        system_prompt=REPO_EXPLORER_PROMPT,
        middleware=[trace_tool_calls("repo-explorer")],
    )


@traceable(name="create_coder_agent", run_type="chain")
def create_coder_agent(
    issue_number: int | None = None,
    on_pr_created: Callable[[str], None] | None = None,
    skill_name: str | None = None,
    effort: str = "moderate",
):
    """Implements code changes and opens a pull request. Receives ONLY the selected skill."""
    prompt = CODER_PROMPT.replace("{issue_number}", str(issue_number or "manual"))
    if skill_name and (skill_body := load_skill(skill_name)):
        prompt = (
            f"{prompt}\n\n"
            f"## Skill Workflow ({skill_name})\n"
            f"Tool Rules:\n"
            f"- For EXISTING files: call `github_read_file` once, then `update_file`.\n"
            f"- For NEW files that do not exist yet: do NOT call `github_read_file` or `update_file`; call `create_file` directly.\n"
            f"- Do NOT call local `ls`, `glob`, `grep`, `read_file`, or `edit_file` tools.\n\n"
            f"{skill_body}"
        )

    return create_deep_agent(
        model=get_model("coder"),
        tools=get_coder_tools(issue_number),
        system_prompt=prompt,
        middleware=[trace_tool_calls("coder", on_pr_created)],
    )


@traceable(name="create_pr_agent", run_type="chain")
def create_pr_agent(
    issue_number: int | None = None,
    on_pull_request_created: Callable[[str], None] | None = None,
    effort: str = "moderate",
):
    """Manages Git branches, commits, and pull requests."""
    return create_deep_agent(
        model=get_model("fast"),
        tools=get_pr_agent_tools(),
        system_prompt=PR_PROMPT.replace(
            "{issue_number}", str(issue_number or "manual")
        ),
        middleware=[trace_tool_calls("pr-agent", on_pull_request_created)],
    )

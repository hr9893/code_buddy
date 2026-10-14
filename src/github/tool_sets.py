import threading
from pathlib import PurePosixPath

from langchain_core.tools import BaseTool, tool
from dotenv import load_dotenv
from langchain_community.agent_toolkits.github.toolkit import GitHubToolkit
from langchain_community.utilities.github import GitHubAPIWrapper
from src.guardrails.command_filter import CommandGuardrail

load_dotenv()

TOOL_NAME_MAPPING = {
    "Get Issues": "get_issues",
    "Get Issue": "get_issue",
    "Comment on Issue": "comment_on_issue",
    "List open pull requests (PRs)": "list_open_pull_requests",
    "Get Pull Request": "get_pull_request",
    "Overview of files included in PR": "get_pr_files_overview",
    "Create Pull Request": "create_pull_request",
    "List Pull Requests' Files": "list_pr_files",
    "Create File": "create_file",
    "Read File": "github_read_file",
    "Update File": "update_file",
    "Delete File": "delete_file",
    "Overview of existing files in Main branch": "get_main_branch_files_overview",
    "Overview of files in current working branch": "get_current_branch_files_overview",
    "List branches in this repository": "list_branches",
    "Set active branch": "set_active_branch",
    "Create a new branch": "create_branch",
    "Get files from a directory": "get_directory_files",
    "Search issues and pull requests": "search_issues_and_prs",
    "Search code": "search_code",
    "Create Commit": "create_commit",
}


def get_raw_github_tools(github: GitHubAPIWrapper | None = None) -> list[BaseTool]:
    """Fetches tools directly from GitHubToolkit and renames them cleanly."""
    github = github or GitHubAPIWrapper()
    toolkit = GitHubToolkit.from_github_api_wrapper(github)
    tools = toolkit.get_tools()
    for t in tools:
        if t.name in TOOL_NAME_MAPPING:
            t.name = TOOL_NAME_MAPPING[t.name]
    return tools


def get_repo_explorer_tools() -> list[BaseTool]:
    """Tools needed by Repo Explorer Subagent: Mapping repo and retrieving code context."""
    github_tools = get_raw_github_tools()
    allowed = [
        "get_main_branch_files_overview",
        "get_directory_files",
        "github_read_file",
        "search_code",
    ]
    selected_github = [t for t in github_tools if t.name in allowed]
    return selected_github


def _single_commit_update_tool(
    github: GitHubAPIWrapper, issue_number: int | None
) -> BaseTool:
    updated_paths: set[str] = set()
    lock = threading.Lock()

    @tool
    def update_file(path: str, content: str) -> str:
        """Replace a file's complete contents on the active GitHub branch.

        Use once per file with the final, complete contents after reading it and
        combining all requested edits. Each successful call creates one commit.
        """
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or ".." in normalized.parts or not path.strip():
            raise ValueError("Provide a relative repository file path.")
        file_path = normalized.as_posix()
        allowed, reason = CommandGuardrail.inspect_file_path(file_path)
        if not allowed:
            raise ValueError(reason)
        branch = github.active_branch
        if not branch or branch == github.github_base_branch:
            raise ValueError("Create a non-base branch before updating files.")

        with lock:
            path_key = file_path.casefold()
            if path_key in updated_paths:
                return (
                    f"{file_path} was already updated during this task. "
                    "Do not call update_file for this path again."
                )

            current = github.github_repo_instance.get_contents(file_path, ref=branch)
            if current.type != "file":
                raise ValueError(f"{file_path} is not a file.")
            old_content = current.decoded_content.decode("utf-8")
            if old_content == content:
                updated_paths.add(path_key)
                return f"No changes needed for {file_path}; no commit was created."

            result = github.github_repo_instance.update_file(
                path=file_path,
                message=(
                    f"Fix issue #{issue_number}: update {file_path}"
                    if issue_number is not None
                    else f"Update {file_path}"
                ),
                content=content,
                branch=branch,
                sha=current.sha,
            )
            updated_paths.add(path_key)
            commit_sha = result["commit"].sha
            return f"Updated {file_path} on branch {branch} in commit {commit_sha}."

    return update_file


def get_coder_tools(issue_number: int | None = None) -> list[BaseTool]:
    """GitHub tools for creating a branch, editing files, and opening a PR."""
    github = GitHubAPIWrapper()
    github_tools = get_raw_github_tools(github)
    allowed = [
        "create_branch",
        "github_read_file",
        "create_file",
        "create_pull_request",
    ]
    tools = [t for t in github_tools if t.name in allowed]
    tools.append(_single_commit_update_tool(github, issue_number))
    return tools


def get_pr_agent_tools() -> list[BaseTool]:
    """GitHub tools for selecting an existing branch and opening its PR."""
    github_tools = get_raw_github_tools()
    allowed = ["set_active_branch", "create_pull_request", "list_branches"]
    return [t for t in github_tools if t.name in allowed]

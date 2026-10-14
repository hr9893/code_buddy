import logging
import threading

from deepagents import create_deep_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_community.utilities.github import GitHubAPIWrapper
from langchain_core.messages import AIMessage
from langsmith import traceable

from src.agents.subagents import (
    create_coder_agent,
    create_pr_agent,
    create_repo_explorer_agent,
)
from src.agents.tracing import (
    ModelCallLimitExceeded,
)
from src.config.llm import get_model
from src.config.settings import settings
from src.memory.episodic import EpisodicMemory
from src.memory.working import TaskState, TaskStatus

log = logging.getLogger("codepilot.orchestrator")

ORCHESTRATOR_PROMPT = """You are the Lead Orchestrator for CodePilot. You receive ONE GitHub issue.
You never read, edit, or run code yourself and you do not plan with todo tools. You delegate with the `task` tool and then report.

Subagents (use as subagent_type):
- coder: implements a code, documentation or configuration change, creates the branch, commits and opens the pull request. Use for bug fixes, features, docs and requested edits.
- repo-explorer: read-only investigation. Use only when the issue asks where or how something works and does NOT request a change. Opens no PR.
- pr-agent: creates or manages a pull request, branch or commit for changes that already exist, without writing code.

Rules:
1. Choose exactly one subagent and call `task` once.
2. The description must be self-contained because the subagent sees nothing else: include the issue number, title and the FULL body verbatim, plus any constraints.
3. Dispatch again only if the subagent reports it could not finish and a different subagent can unblock it (for example coder cannot locate the code, so use repo-explorer, then coder again). At most 3 dispatches in total. Never repeat a call with an identical description.
4. When the subagent returns, answer in 2-3 sentences: what was done, the approach, files involved, and the PR URL if one exists. If blocked, say so and why.
"""


def _record_dispatches(dispatched: list[str]):
    @wrap_tool_call
    def recorder(request, handler):
        call = request.tool_call
        if call["name"] == "task":
            name = call["args"].get("subagent_type", "unknown")
            dispatched.append(name)
            log.info("Dispatching issue to subagent=%s", name)
        return handler(request)

    return recorder


def fetch_open_issues() -> list[dict]:
    github = GitHubAPIWrapper(
        github_repository=settings.github_repository,
        github_app_id=settings.github_app_id,
        github_app_private_key=settings.github_app_private_key,
    )
    return [
        {"number": i.number, "title": i.title, "body": i.body or ""}
        for i in github.github_repo_instance.get_issues(state="open")
        if i.pull_request is None
    ]


class Orchestrator:
    def __init__(self):
        self.episodic = EpisodicMemory(settings.sqlite_path)
        self.in_progress: set[int] = set()
        self._stop = threading.Event()
        self._session_ended = False
        self.episodic.start_session()

    @traceable(name="process_issue")
    def process_issue(self, number: int | None, title: str, body: str = "") -> TaskState:
        log.info("Starting issue #%s: %s", number, title)
        state = TaskState(issue_number=number, title=title, body=body)
        prs: list[str] = []
        dispatched: list[str] = []
        completed = False

        try:
            task = f"Issue #{number}: {title}\n\n{body}".strip()
            state.advance(TaskStatus.EXPLORING)

            subagents = [
                {
                    "name": "repo-explorer",
                    "description": (
                        "Investigates the repository without modifying code. "
                        "Use for questions about how the code works."
                    ),
                    "runnable": create_repo_explorer_agent(),
                },
                {
                    "name": "coder",
                    "description": (
                        "Implements code, documentation, or configuration changes "
                        "and creates a pull request."
                    ),
                    "runnable": create_coder_agent(number, prs.append),
                },
                {
                    "name": "pr-agent",
                    "description": (
                        "Manages branches, commits, and pull requests for "
                        "changes that already exist."
                    ),
                    "runnable": create_pr_agent(number, prs.append),
                },
            ]

            agent = create_deep_agent(
                model=get_model(),
                tools=[],
                system_prompt=ORCHESTRATOR_PROMPT,
                subagents=subagents,
                middleware=[
                    _record_dispatches(dispatched),
                ],
            )

            result = agent.invoke({"messages": [{"role": "user", "content": task}]})

            messages = result.get("messages", [])
            summary = next(
                (
                    message.content
                    for message in reversed(messages)
                    if isinstance(message, AIMessage) and message.content
                ),
                None,
            )

            if summary:
                log.info("Orchestrator summary for issue #%s: %s",number,summary,)

            # An investigation can complete without creating a PR.
            investigation_only = (
                    bool(dispatched)
                    and set(dispatched) == {"repo-explorer"})

            completed = bool(prs) or investigation_only

            if not dispatched:
                log.error("Issue #%s finished without dispatching to a subagent",number,)
            elif not completed:
                log.error("Issue #%s finished without a confirmed PR (dispatched=%s)",number,dispatched,)
        except Exception:
            log.exception("Issue #%s crashed", number)

        state.task_type = dispatched[0] if dispatched else "none"
        state.advance(TaskStatus.DONE if completed else TaskStatus.FAILED)
        self._finish(state)
        return state

    def _finish(self, state: TaskState) -> None:
        self.episodic.record_task(state)
        log.info(
            "Issue #%s finished: %s (%.0fs)",
            state.issue_number,
            state.status.value,
            state.duration_s,
        )
        state.clear()

    def poll_once(self) -> None:
        skip = (
            self.in_progress
            | self.episodic.done_issues()
            | self.episodic.recently_failed_issues(settings.episodic_lookback_sessions)
        )
        pending = [i for i in fetch_open_issues() if i["number"] not in skip]
        if not pending:
            log.info("No eligible issues in %s", settings.github_repository)
            return

        log.info("Found %d eligible issue(s)", len(pending))
        for issue in pending[
            :1
        ]:  # one issue per poll while debugging; remove the slice later
            if self._stop.is_set():
                break
            self.in_progress.add(issue["number"])
            try:
                self.process_issue(issue["number"], issue["title"], issue["body"])
            finally:
                self.in_progress.discard(issue["number"])

    def run_forever(self) -> None:
        self._stop.clear()
        if self._session_ended:
            self.episodic.start_session()
            self._session_ended = False
        log.info("Polling every %s min", settings.poll_interval_minutes)
        try:
            while not self._stop.is_set():
                try:
                    self.poll_once()
                except Exception:
                    log.exception("Poll failed")
                self._stop.wait(settings.poll_interval_minutes * 60)
        finally:
            log.info("Session summary: %s", self.episodic.end_session())
            self._session_ended = True

    def stop(self) -> None:
        self._stop.set()

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
from src.classifier.issue_classifier import classify_issue
from src.config.system_prompts import ORCHESTRATOR_PROMPT
from src.config.llm import get_model
from src.config.settings import settings
from src.memory.episodic import EpisodicMemory
from src.memory.working import TaskState, TaskStatus
from src.skills.skill_loader import select_skill

log = logging.getLogger("codepilot.orchestrator")

def _record_dispatches(dispatched: list[str]):
    @wrap_tool_call
    def recorder(request, handler):
        if request.tool_call["name"] == "task":
            name = request.tool_call["args"].get("subagent_type", "unknown")
            dispatched.append(name)
            log.info(f"Dispatching issue to subagent={name}")
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
        if not i.pull_request
    ]

class Orchestrator:
    def __init__(self):
        self.episodic = EpisodicMemory(settings.sqlite_path)
        self.in_progress: set[int] = set()
        self._stop = threading.Event()
        self._session_ended = False
        self.episodic.start_session()

    @traceable(name="process_issue")
    def process_issue(self, number: int, title: str, body: str = "") -> TaskState:
        log.info(f"Starting issue #{number}: {title}")
        state = TaskState(issue_number=number, title=title, body=body)
        state.advance(TaskStatus.EXPLORING)

        selected_skill = select_skill(title, body)
        log.info(f"Selected skill for issue #{number}: {selected_skill or 'none'}")

        prs, dispatched, completed = [], [], False

        decision = classify_issue(title, body)
        if not decision.is_safe:
            log.error(f"Issue #{number} blocked by Jev safety gate")
            state.task_type = "blocked"
            state.advance(TaskStatus.FAILED)
            self.episodic.record_task(state)
            state.clear()
            return state

        subagents = [
            {
                "name": "repo-explorer",
                "description": "Read-only investigation.",
                "runnable": create_repo_explorer_agent(effort=decision.effort),
            },
            {
                "name": "coder",
                "description": "Implements code changes and opens PRs.",
                "runnable": create_coder_agent(
                    number,
                    prs.append,
                    skill_name=decision.skill_name,
                    effort=decision.effort,
                ),
            },
            {
                "name": "pr-agent",
                "description": "Manages PRs for existing changes.",
                "runnable": create_pr_agent(number, prs.append, effort=decision.effort),
            },
        ]

        agent = create_deep_agent(
            model=get_model(),
            tools=[],
            system_prompt=ORCHESTRATOR_PROMPT,
            subagents=subagents,
            middleware=[_record_dispatches(dispatched)],
        )

        try:
            task_content = f"Issue #{number}: {title}\n\n{body}".strip()
            result = agent.invoke({"messages": [{"role": "user", "content": task_content}]})

            if summary := next(
                (m.content for m in reversed(result.get("messages", [])) if isinstance(m, AIMessage) and m.content),
                None,
            ):
                log.info(f"Orchestrator summary for issue #{number}: {summary}")

            completed = bool(prs) or set(dispatched) == {"repo-explorer"}
            if not dispatched:
                log.error(f"Issue #{number} finished without dispatching to a subagent")
            elif not completed:
                log.error(f"Issue #{number} finished without a confirmed PR. Dispatched: {dispatched}")
        except Exception:
            log.exception(f"Issue #{number} crashed")

        state.task_type = "coder" if "coder" in dispatched else (dispatched[0] if dispatched else "none")
        state.advance(TaskStatus.DONE if completed else TaskStatus.FAILED)
        self.episodic.record_task(state)
        log.info(f"Issue #{state.issue_number} finished: {state.status.value} ({state.duration_s:.0f}s)")
        state.clear()
        return state

    def poll_once(self) -> None:
        skip = (
            self.in_progress
            | self.episodic.done_issues()
            | self.episodic.recently_failed_issues(settings.episodic_lookback_sessions)
        )
        issue = next((i for i in fetch_open_issues() if i["number"] not in skip), None)
        if not issue or self._stop.is_set():
            log.info(f"No eligible issues in {settings.github_repository}")
            return

        self.in_progress.add(issue["number"])
        try:
            self.process_issue(**issue)
        finally:
            self.in_progress.discard(issue["number"])

    def run_forever(self) -> None:
        self._stop.clear()
        if self._session_ended:
            self.episodic.start_session()
            self._session_ended = False

        log.info(f"Polling every {settings.poll_interval_minutes} min")
        try:
            while not self._stop.is_set():
                try:
                    self.poll_once()
                except Exception:
                    log.exception("Poll failed")
                self._stop.wait(settings.poll_interval_minutes * 60)
        finally:
            log.info(f"Session summary: {self.episodic.end_session()}")
            self._session_ended = True

    def stop(self) -> None:
        self._stop.set()
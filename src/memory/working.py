import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum


class TaskStatus(str, Enum):
    TRIAGED = "TRIAGED"
    EXPLORING = "EXPLORING"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    PR_OPENED = "PR_OPENED"
    DONE = "DONE"
    FAILED = "FAILED"


S = TaskStatus
_ALLOWED = {
    S.TRIAGED: {S.EXPLORING},
    S.EXPLORING: {S.IMPLEMENTING, S.DONE},
    S.IMPLEMENTING: {S.TESTING},
    S.TESTING: {S.IMPLEMENTING, S.PR_OPENED},  # back to IMPLEMENTING = retry
    S.PR_OPENED: {S.DONE},
    S.DONE: set(),
    S.FAILED: set(),
}


@dataclass
class TaskState:
    issue_number: int | None            # None for free-form tasks typed in the TUI
    title: str
    body: str = ""
    task_type: str = ""
    status: TaskStatus = TaskStatus.TRIAGED
    repo_map_path: str = ""
    relevant_files: list[str] = field(default_factory=list)   # paths only, never contents
    files_modified: list[str] = field(default_factory=list)
    diff_path: str = ""
    test_results: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (S.DONE, S.FAILED)

    @property
    def duration_s(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def advance(self, new: TaskStatus) -> None:
        if self.is_terminal:
            raise ValueError(f"Task already {self.status.value}")
        if new != S.FAILED and new not in _ALLOWED[self.status]:
            raise ValueError(f"Illegal transition {self.status.value} -> {new.value}")
        self.status = new
        if self.is_terminal:
            self.finished_at = time.time()

    def to_prompt(self) -> str:
        """JSON handed to a subagent at spawn time instead of relying on chat history."""
        return json.dumps(asdict(self), default=str, indent=2)

    def clear(self) -> None:
        """Call AFTER the episode has been recorded; keeps only identity + outcome."""
        self.body = self.repo_map_path = self.diff_path = ""
        self.relevant_files.clear()
        self.test_results.clear()
        self.lessons.clear()
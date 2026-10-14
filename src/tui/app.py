import logging
import shlex
import sys
import threading
from collections import deque
from datetime import datetime
from typing import Callable

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout

load_dotenv()

from src.config.settings import settings  # noqa: E402
from src.guardrails import middleware as guard  # noqa: E402
from src.orchestrator.orchestrator import Orchestrator  # noqa: E402

LOG = logging.getLogger("codepilot.console")
COMMANDS = (
    "start",
    "stop",
    "status",
    "history",
    "logs",
    "clear",
    "help",
    "approve",
    "reject",
    "quit",
)


class ConsoleLogHandler(logging.StreamHandler):
    """Write normal selectable log lines to the active terminal prompt."""

    def __init__(self, stream):
        super().__init__(stream)
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-8s %(message)s",
                datefmt="%H:%M:%S",
            )
        )


class CodePilotConsole:
    def __init__(self):
        self.orchestrator: Orchestrator | None = None
        self.run_state = "STARTING"
        self._boot_error: Exception | None = None
        self._boot_complete = threading.Event()
        self._boot_thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._approval_event: threading.Event | None = None
        self._approval_result: dict[str, bool] | None = None
        self._approval_lock = threading.Lock()
        self._recent_logs: deque[str] = deque(maxlen=500)
        self._quit = False
        self.session: PromptSession | None = None
        self._log_handler: ConsoleLogHandler | None = None

    def _configure_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.WARNING)
        for handler in root.handlers[:]:
            if isinstance(handler, ConsoleLogHandler):
                root.removeHandler(handler)

        handler = ConsoleLogHandler(sys.stdout)
        handler.addFilter(self._remember_log)
        root.addHandler(handler)
        self._log_handler = handler
        logging.getLogger("codepilot").setLevel(logging.INFO)

    def _remember_log(self, record: logging.LogRecord) -> bool:
        self._recent_logs.append(handler_line(record))
        return True

    def run(self) -> None:
        guard.approval_handler = self.ask_approval

        print("Code Buddy  |  Autonomous GitHub issue agent")
        print(f"Repository: {settings.github_repository}")
        print("Type 'help' for commands. Live output appears above the prompt.")
        print()
        try:
            if sys.stdin.isatty() and sys.stdout.isatty():
                with patch_stdout():
                    self._run_console(self._command_loop)
            else:
                self._run_console(self._plain_command_loop)
        finally:
            guard.approval_handler = None

    def _run_console(self, command_loop: Callable[[], None]) -> None:
        try:
            self._start()
            command_loop()
        except KeyboardInterrupt:
            print("\nInterrupt received.")
        finally:
            self._shutdown()

    def _start(self) -> None:
        self._configure_logging()
        LOG.info("Loading issue history...")
        self._boot_thread = threading.Thread(
            target=self._boot,
            name="codepilot-boot",
            daemon=True,
        )
        self._boot_thread.start()

    def _boot(self) -> None:
        try:
            orchestrator = Orchestrator()
        except Exception as error:
            self._boot_error = error
            LOG.exception("Application startup failed")
        else:
            with self._state_lock:
                self.orchestrator = orchestrator
                self.run_state = "STOPPED"
            LOG.info("Ready. Use 'start' to begin polling.")
        finally:
            self._boot_complete.set()

    def _command_loop(self) -> None:
        if self.session is None:
            self.session = PromptSession(
                history=InMemoryHistory(),
                completer=WordCompleter(COMMANDS, sentence=True),
                complete_while_typing=True,
            )
        while not self._quit:
            try:
                command = self.session.prompt(
                    HTML("<ansigreen>code-buddy</ansigreen> <ansiblue>›</ansiblue> "),
                    bottom_toolbar=self._toolbar,
                    prompt_continuation=" " * 13,
                )
            except EOFError:
                self._quit = True
                continue
            except KeyboardInterrupt:
                print("Use 'quit' to stop Code Buddy.")
                continue
            if command.strip():
                self._handle_command(command.strip())

    def _plain_command_loop(self) -> None:
        while not self._quit:
            try:
                command = input("code-buddy > ")
            except EOFError:
                self._quit = True
                continue
            if command.strip():
                self._handle_command(command.strip())

    def _toolbar(self):
        with self._state_lock:
            state = self.run_state
        return (
            f" {state}  |  {settings.github_repository}  |  "
            "start · stop · status · history · logs · quit"
        )

    def _handle_command(self, command_line: str) -> None:
        try:
            args = shlex.split(command_line)
        except ValueError as error:
            print(f"Invalid command: {error}")
            return
        if not args:
            return

        command = args[0].lower()
        if command in {"q", "exit"}:
            command = "quit"
        elif command == "s":
            command = "start"

        if command == "help":
            self._show_help()
        elif command == "start":
            self.start()
        elif command == "stop":
            self.stop()
        elif command == "status":
            self.show_status()
        elif command == "history":
            self.show_history()
        elif command == "logs":
            self.show_logs(args[1] if len(args) > 1 else None)
        elif command == "clear":
            self.clear_screen()
        elif command == "approve":
            self.resolve_approval(True)
        elif command == "reject":
            self.resolve_approval(False)
        elif command == "quit":
            self._quit = True
        else:
            print(f"Unknown command: {args[0]}. Type 'help' to see available commands.")

    @staticmethod
    def _show_help() -> None:
        print(
            "Commands:\n"
            "  start             Start polling GitHub for open issues\n"
            "  stop              Finish the current issue, then stop polling\n"
            "  status            Show poller and task counters\n"
            "  history           Show recent issue outcomes\n"
            "  logs [N]          Print the last N log lines (default 50)\n"
            "  clear             Clear the visible terminal screen\n"
            "  approve / reject  Respond to a pending guarded action\n"
            "  help              Show this command list\n"
            "  quit              Stop polling and exit\n"
            "\n"
            "Logs are ordinary terminal text. Select and copy them with the "
            "PowerShell terminal, or use 'logs' to print them again."
        )

    def start(self) -> None:
        if not self._boot_complete.wait(timeout=0):
            print("Still loading issue history; try 'start' again shortly.")
            return
        if self._boot_error:
            print("Startup failed; see the exception in the log above.")
            return
        with self._state_lock:
            if self.run_state in {"RUNNING", "STOPPING"}:
                print(f"Polling is already {self.run_state.lower()}.")
                return
            if self.orchestrator is None:
                print("Orchestrator has not initialized.")
                return
            self.run_state = "RUNNING"
            self._poll_thread = threading.Thread(
                target=self._poll,
                name="codepilot-poller",
                daemon=True,
            )
            self._poll_thread.start()
        LOG.info(
            "Polling started; interval is %s minutes.", settings.poll_interval_minutes
        )

    def _poll(self) -> None:
        try:
            if self.orchestrator is None:
                raise RuntimeError("Orchestrator is not initialized.")
            self.orchestrator.run_forever()
        except Exception:
            LOG.exception("Polling worker crashed")
            with self._state_lock:
                self.run_state = "ERROR"
        else:
            with self._state_lock:
                self.run_state = "STOPPED"
            LOG.info("Polling stopped.")

    def stop(self) -> None:
        with self._state_lock:
            if self.run_state != "RUNNING":
                print(f"Polling is {self.run_state.lower()}.")
                return
            self.run_state = "STOPPING"
            orchestrator = self.orchestrator
        if orchestrator:
            orchestrator.stop()
        LOG.info("Stopping after the current issue finishes.")

    def show_status(self) -> None:
        with self._state_lock:
            print(f"State:      {self.run_state}")
            print(f"Repository: {settings.github_repository}")
            print(f"Poll rate:  every {settings.poll_interval_minutes} minutes")
            orchestrator = self.orchestrator
        if orchestrator:
            print(f"Succeeded:  {orchestrator.episodic.done_count()}")
            print(f"Failed:     {orchestrator.episodic.failed_count()}")
        elif self._boot_error:
            print(f"Startup error: {self._boot_error}")
        else:
            print("Startup:    still initializing")

    def show_history(self) -> None:
        if not self.orchestrator:
            print("History is available after startup finishes.")
            return
        rows = self.orchestrator.episodic.recent_attempts(20)
        if not rows:
            print("No issue attempts recorded yet.")
            return
        print(f"{'WHEN':<18} {'ISSUE':<9} {'TYPE':<20} {'RESULT':<10} DURATION")
        for timestamp, issue, kind, outcome, duration in rows:
            when = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
            issue_text = f"#{issue}" if issue is not None else "-"
            print(
                f"{when:<18} {issue_text:<9} {(kind or '-'):<20} "
                f"{outcome:<10} {(duration or 0):.0f}s"
            )

    def show_logs(self, count_arg: str | None) -> None:
        try:
            count = (
                min(max(int(count_arg), 1), self._recent_logs.maxlen or 500)
                if count_arg
                else 50
            )
        except ValueError:
            print("Usage: logs [number]")
            return
        lines = list(self._recent_logs)[-count:]
        if not lines:
            print("No log lines recorded.")
            return
        print("\n".join(lines))

    @staticmethod
    def clear_screen() -> None:
        if sys.stdout.isatty():
            print("\033[2J\033[H", end="", flush=True)

    def ask_approval(self, command: str) -> bool:
        event = threading.Event()
        result = {"approved": False}
        with self._approval_lock:
            if self._approval_event is not None:
                LOG.error(
                    "Another guarded command requested approval while one is pending."
                )
                return False
            self._approval_event = event
            self._approval_result = result
        LOG.warning(
            "Approval required. Review the command below, then enter 'approve' or 'reject':\n%s",
            command,
        )
        answered = event.wait(timeout=300)
        with self._approval_lock:
            self._approval_event = None
            self._approval_result = None
        if not answered:
            LOG.warning("Approval timed out; rejecting the guarded action.")
            return False
        return result["approved"]

    def resolve_approval(self, approved: bool) -> None:
        with self._approval_lock:
            event, result = self._approval_event, self._approval_result
            if event is None or result is None:
                print("There is no action waiting for approval.")
                return
            result["approved"] = approved
            event.set()
        LOG.info("Guarded action %s.", "approved" if approved else "rejected")

    def _shutdown(self) -> None:
        with self._approval_lock:
            if self._approval_event is not None and self._approval_result is not None:
                self._approval_result["approved"] = False
                self._approval_event.set()
        if self.orchestrator and self._poll_thread and self._poll_thread.is_alive():
            self.stop()
            print("Waiting for the current issue to finish before exiting...")
            self._poll_thread.join()
        print("Code Buddy stopped.")
        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler.close()
            self._log_handler = None


def handler_line(record: logging.LogRecord) -> str:
    timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
    line = f"{timestamp}  {record.levelname:<8} {record.getMessage()}"
    if record.exc_info:
        line += "\n" + logging.Formatter().formatException(record.exc_info)
    return line


def main() -> None:
    CodePilotConsole().run()


if __name__ == "__main__":
    main()

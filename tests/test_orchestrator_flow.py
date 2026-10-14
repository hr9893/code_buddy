import unittest
from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import Mock, patch

from deepagents import create_deep_agent as build_deep_agent
from deepagents.profiles.harness.harness_profiles import (
    _harness_profile_for_model,
)
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, StateGraph

import src.orchestrator.orchestrator as orchestrator_module
import src.agents.subagents as subagents_module
from src.agents.tracing import MODEL_CALL_LIMITS, ModelCallLimitExceeded
from src.memory.working import TaskState, TaskStatus


class FakeRunnable:
    def __init__(self):
        self.config = None

    def with_config(self, config):
        self.config = config
        return self


class FakeAgent:
    def __init__(self, options, dispatch=None, create_pr=False, error=None):
        self.options = options
        self.dispatch = dispatch
        self.create_pr = create_pr
        self.error = error

    def invoke(self, *_args, **_kwargs):
        if self.dispatch:
            recorder = next(
                middleware
                for middleware in self.options["middleware"]
                if middleware.name == "recorder"
            )
            request = SimpleNamespace(
                tool_call={
                    "name": "task",
                    "args": {"subagent_type": self.dispatch},
                    "id": "1",
                }
            )
            recorder.wrap_tool_call(request, lambda _request: "delegated")
            if self.create_pr:
                factory = {
                    "coder": orchestrator_module.create_coder_agent,
                    "pr-agent": orchestrator_module.create_pr_agent,
                }[self.dispatch]
                factory.call_args.args[2]("Successfully created PR #31")
        if self.error:
            raise self.error
        return {"messages": [AIMessage(content="Task handled.")]}


class OrchestratorFlowTests(unittest.TestCase):
    def setUp(self):
        self.episodic = Mock()
        self.episodic.done_issues.return_value = set()
        self.episodic.recently_failed_issues.return_value = set()
        with patch.object(
            orchestrator_module, "EpisodicMemory", return_value=self.episodic
        ):
            self.orchestrator = orchestrator_module.Orchestrator()

        self.states = []

        def make_state(*args, **kwargs):
            state = TaskState(*args, **kwargs)
            state.clear = Mock(wraps=state.clear)
            self.states.append(state)
            return state

        self.patches = [
            patch.object(orchestrator_module, "TaskState", side_effect=make_state),
            patch.object(orchestrator_module, "create_repo_explorer_agent"),
            patch.object(orchestrator_module, "create_coder_agent"),
            patch.object(orchestrator_module, "create_pr_agent"),
            patch.object(orchestrator_module, "create_deep_agent"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        orchestrator_module.create_repo_explorer_agent.return_value = FakeRunnable()
        orchestrator_module.create_coder_agent.return_value = FakeRunnable()
        orchestrator_module.create_pr_agent.return_value = FakeRunnable()
        self.agent_options = None
        self.dispatch = None
        self.create_pr = False
        self.error = None

        def build_agent(**options):
            self.agent_options = options
            return FakeAgent(
                options,
                dispatch=self.dispatch,
                create_pr=self.create_pr,
                error=self.error,
            )

        orchestrator_module.create_deep_agent.side_effect = build_agent

    def run_issue(self, dispatch=None, create_pr=False, error=None):
        self.dispatch = dispatch
        self.create_pr = create_pr
        self.error = error
        state = self.orchestrator.process_issue(31, "Example issue", "Issue body")
        self.episodic.record_task.assert_called_once_with(state)
        state.clear.assert_called_once_with()
        return state

    def test_coder_with_confirmed_pr_completes(self):
        state = self.run_issue("coder", create_pr=True)
        self.assertEqual(state.status, TaskStatus.DONE)
        self.assertEqual(state.task_type, "coder")

    def test_repo_explorer_completes_without_pr(self):
        state = self.run_issue("repo-explorer")
        self.assertEqual(state.status, TaskStatus.DONE)
        self.assertEqual(state.task_type, "repo-explorer")

    def test_coder_without_pr_fails(self):
        state = self.run_issue("coder")
        self.assertEqual(state.status, TaskStatus.FAILED)
        self.assertEqual(state.task_type, "coder")

    def test_no_dispatch_fails(self):
        state = self.run_issue()
        self.assertEqual(state.status, TaskStatus.FAILED)
        self.assertEqual(state.task_type, "none")

    def test_model_limit_with_pr_completes(self):
        state = self.run_issue(
            "coder", create_pr=True, error=ModelCallLimitExceeded("budget")
        )
        self.assertEqual(state.status, TaskStatus.DONE)

    def test_model_limit_without_pr_fails(self):
        state = self.run_issue("coder", error=ModelCallLimitExceeded("budget"))
        self.assertEqual(state.status, TaskStatus.FAILED)

    def test_generic_exception_fails(self):
        state = self.run_issue("coder", error=RuntimeError("agent failed"))
        self.assertEqual(state.status, TaskStatus.FAILED)

    def test_subagent_recursion_configs_are_bound(self):
        self.run_issue("coder", create_pr=True)
        subagents = {
            subagent["name"]: subagent["runnable"]
            for subagent in self.agent_options["subagents"]
        }
        for name, runnable in subagents.items():
            self.assertEqual(
                runnable.config,
                {"recursion_limit": MODEL_CALL_LIMITS["moderate"][name] * 3 + 5},
            )
        self.assertEqual(self.agent_options["middleware"][0].name, "trace_model_call")

    def test_compiled_orchestrator_has_task_tool(self):
        model = ChatOpenAI(
            model="deepseek-chat",
            api_key="test-key",
            base_url="https://api.deepseek.com",
        )
        agent = build_deep_agent(
            model=model,
            tools=[],
            system_prompt="Delegate the task.",
            subagents=[
                {
                    "name": "coder",
                    "description": "Implement changes.",
                    "runnable": RunnableLambda(lambda state: state),
                }
            ],
        )
        tools = agent.get_graph().nodes["tools"].data.tools_by_name
        self.assertIn("task", tools)
        profile = _harness_profile_for_model(model, None)
        self.assertNotIn("task", profile.excluded_tools)
        self.assertTrue(
            {"ls", "read_file", "write_file", "edit_file", "execute"}.issubset(
                profile.excluded_tools
            )
        )
        self.assertFalse(profile.general_purpose_subagent.enabled)

    def test_specialists_do_not_get_a_task_tool(self):
        model = ChatOpenAI(
            model="deepseek-chat",
            api_key="test-key",
            base_url="https://api.deepseek.com",
        )
        with (
            patch.object(subagents_module, "get_model", return_value=model),
            patch.object(subagents_module, "get_repo_explorer_tools", return_value=[]),
            patch.object(subagents_module, "get_coder_tools", return_value=[]),
            patch.object(subagents_module, "get_pr_agent_tools", return_value=[]),
        ):
            agents = [
                subagents_module.create_repo_explorer_agent(),
                subagents_module.create_coder_agent(31),
                subagents_module.create_pr_agent(31),
            ]
        for agent in agents:
            tools = agent.get_graph().nodes["tools"].data.tools_by_name
            self.assertNotIn("task", tools)

    def test_poll_once_uses_fetch_open_issues(self):
        with patch.object(orchestrator_module, "fetch_open_issues", return_value=[]):
            self.orchestrator.poll_once()

    def test_small_subagent_recursion_limit_is_enforced(self):
        class LoopState(TypedDict):
            count: int

        graph = StateGraph(LoopState)
        graph.add_node("loop", lambda state: {"count": state["count"] + 1})
        graph.add_edge(START, "loop")
        graph.add_edge("loop", "loop")
        runnable = graph.compile().with_config({"recursion_limit": 1})
        with self.assertRaises(GraphRecursionError):
            runnable.invoke({"count": 0})


if __name__ == "__main__":
    unittest.main()

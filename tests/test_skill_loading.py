from unittest.mock import MagicMock, patch

from src.agents.subagents import (
    create_coder_agent,
    create_pr_agent,
    create_repo_explorer_agent,
)
from src.skills import skill_loader


def test_metadata_discovery_does_not_load_full_skill_bodies():
    """Verify list_skill_metadata reads only name/description and never calls load_skill."""
    with patch.object(
        skill_loader, "load_skill", wraps=skill_loader.load_skill
    ) as spy_load:
        catalogue = skill_loader.list_skill_metadata()
        spy_load.assert_not_called()

    names = {item["name"] for item in catalogue}
    assert {
        "bug_fix",
        "dependency_update",
        "documentation",
        "feature_addition",
    } <= names
    for item in catalogue:
        assert "name" in item and "description" in item


def test_select_skill_picks_single_relevant_skill_without_loading_bodies():
    """Verify select_skill chooses the matching skill using metadata only."""
    with patch.object(
        skill_loader, "load_skill", wraps=skill_loader.load_skill
    ) as spy_load:
        assert (
            skill_loader.select_skill("Fix TypeError crash in login handler")
            == "bug_fix"
        )
        assert (
            skill_loader.select_skill("Bump pydantic version in pyproject.toml")
            == "dependency_update"
        )
        assert (
            skill_loader.select_skill("Update README documentation with setup steps")
            == "documentation"
        )
        assert (
            skill_loader.select_skill("Where is the database connection initialized?")
            is None
        )
        spy_load.assert_not_called()


def test_only_selected_skill_is_loaded_and_passed_only_to_coder():
    """Verify coder receives only the 1 selected skill and other agents receive 0 skills."""
    with (
        patch(
            "src.agents.subagents.create_deep_agent", return_value=MagicMock()
        ) as mock_deep_agent,
        patch("src.agents.subagents.get_model", return_value=MagicMock()),
        patch("src.agents.subagents.get_repo_explorer_tools", return_value=[]),
        patch("src.agents.subagents.get_coder_tools", return_value=[]),
        patch("src.agents.subagents.get_pr_agent_tools", return_value=[]),
        patch(
            "src.agents.subagents.load_skill", wraps=skill_loader.load_skill
        ) as spy_load,
    ):
        create_repo_explorer_agent()
        create_pr_agent(issue_number=42)
        create_coder_agent(issue_number=42, skill_name="bug_fix")

        # load_skill called exactly once, only for "bug_fix"
        spy_load.assert_called_once_with("bug_fix")

        explorer_prompt = mock_deep_agent.call_args_list[0].kwargs["system_prompt"]
        pr_prompt = mock_deep_agent.call_args_list[1].kwargs["system_prompt"]
        coder_prompt = mock_deep_agent.call_args_list[2].kwargs["system_prompt"]

        bug_skill_body = skill_loader.load_skill("bug_fix")
        doc_skill_body = skill_loader.load_skill("documentation")

        assert bug_skill_body in coder_prompt
        assert doc_skill_body not in coder_prompt
        assert "## Skill Workflow" not in explorer_prompt
        assert "## Skill Workflow" not in pr_prompt

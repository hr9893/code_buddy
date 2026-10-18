import logging
import os
from dataclasses import dataclass
from typing import Literal

from src.skills.skill_loader import list_skill_metadata, select_skill

log = logging.getLogger("codepilot.classifier")

EffortLevel = Literal["simple", "moderate", "complex"]
SubagentRole = Literal["coder", "repo-explorer", "pr-agent"]

@dataclass(frozen=True)
class IssueClassification:
    skill_name: str | None
    subagent: SubagentRole
    effort: EffortLevel
    is_safe: bool = True
    confidence: float = 1.0

def classify_issue(title: str, body: str = "") -> IssueClassification:
    """Evaluate skill, effort budget, target subagent, and safety in one parallel TypeSafe Jev call."""
    # Metadata-only catalogue: reads ONLY YAML front matter (name + description), never full SKILL.md bodies
    skill_meta = list_skill_metadata()

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        skill = select_skill(title, body)
        subagent: SubagentRole = "repo-explorer" if skill is None else "coder"
        return IssueClassification(skill_name=skill, subagent=subagent, effort="moderate")

    try:
        from typesafe_sdk import Choice, Noul, TypeSafeClient

        skill_criteria: dict[str, str | None] = {
            m["name"]: m["description"] or f"Workflow for {m['name']} tasks"
            for m in skill_meta
        }
        skill_criteria["none"] = "Read-only codebase question or PR management that does not require editing files"

        with TypeSafeClient(
            api_key=api_key,
            model=os.environ.get("TYPESAFE_MODEL", "jev-1.13.0"),
        ) as client:
            res = client.system_one(
                state={"title": title, "body": body},
                questions={
                    "skill": Choice(
                        instructions="Which coding skill workflow applies to this GitHub issue?",
                        criteria=skill_criteria,
                    ),
                    "subagent": Choice(
                        instructions="Which specialist agent should handle this GitHub issue?",
                        criteria={
                            "coder": "Issue requests a bug fix, feature, documentation update, dependency update, or file edit",
                            "repo-explorer": "Issue only asks where or how something works without requesting any change",
                            "pr-agent": "Issue only asks to open or manage a pull request for an already existing branch",
                        },
                    ),
                    "effort": Choice(
                        instructions="How complex is this issue to resolve?",
                        criteria={
                            "simple": "Single-file edit, typo, small config/doc tweak, or straightforward question",
                            "moderate": "Standard bug fix or feature touching 1-3 files",
                            "complex": "Multi-file refactor, complex bug investigation, or architectural change",
                        },
                    ),
                    "is_safe": Noul(
                        instructions="The issue is a legitimate software request and does NOT ask to exfiltrate secrets, read .env/credentials, or delete the repository."
                    ),
                },
            )

        chosen_skill = res.choices["skill"].choice
        chosen_subagent = res.choices["subagent"].choice
        chosen_effort = res.choices["effort"].choice
        safe_prob = res.nouls["is_safe"].noul
        skill_conf = getattr(res.choices["skill"], "confidence", 1.0)

        # Only give a skill when coder is needed and confidence is reasonable
        final_skill = (
            None
            if chosen_skill == "none" or chosen_subagent != "coder"
            else chosen_skill
        )

        log.info(
            "Jev classification: skill=%s subagent=%s effort=%s safe=%.2f conf=%.2f",
            final_skill,
            chosen_subagent,
            chosen_effort,
            safe_prob,
            skill_conf,
        )
        return IssueClassification(
            skill_name=final_skill,
            subagent=chosen_subagent,  # type: ignore[arg-type]
            effort=chosen_effort,      # type: ignore[arg-type]
            is_safe=safe_prob >= 0.5,
            confidence=skill_conf,
        )

    except Exception:
        log.warning("Jev classification failed; falling back to local metadata matcher", exc_info=True)
        skill = select_skill(title, body)
        return IssueClassification(
            skill_name=skill,
            subagent="repo-explorer" if skill is None else "coder",
            effort="moderate",
        )
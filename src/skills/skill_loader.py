from pathlib import Path

_ROOT = Path(__file__).parent / "repository"

# Lightweight keyword triggers used alongside front-matter metadata for fast classification
_SKILL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dependency_update": ("dependency", "dependencies", "bump", "upgrade", "version", "lockfile", "requirements", "pyproject", "package"),
    "documentation": ("doc", "docs", "documentation", "readme", "typo", "comment", "docstring", "changelog"),
    "bug_fix": ("bug", "fix", "error", "exception", "crash", "fail", "failing", "broken", "issue", "regression", "traceback"),
    "feature_addition": ("feature", "add", "implement", "support", "enhance", "enhancement", "new", "create"),
}

_INVESTIGATION_ONLY_HINTS = ("where is", "how does", "explain", "investigate", "find where", "question:")

def _skill_path(name: str) -> Path:
    return _ROOT / name.removesuffix("_skill") / "SKILL.md"

def get_skill_metadata(name: str) -> dict[str, str]:
    """Read ONLY the YAML front matter (name, description) without loading the skill body."""
    skill_id = name.removesuffix("_skill")
    path = _skill_path(skill_id)
    if not path.is_file():
        return {}

    metadata: dict[str, str] = {"name": skill_id, "description": ""}
    with path.open(encoding="utf-8") as f:
        first_line = f.readline().strip()
        if first_line != "---":
            return metadata
        for line in f:
            stripped = line.strip()
            if stripped == "---":
                break
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip().lower()
                if key in ("name", "description"):
                    metadata[key] = value.strip().strip("\"'")
    metadata["name"] = metadata["name"].removesuffix("_skill") or skill_id
    return metadata

def list_skill_metadata() -> list[dict[str, str]]:
    """Return lightweight metadata (name, description) for all available skills at startup."""
    if not _ROOT.is_dir():
        return []
    return [
        meta
        for folder in sorted(_ROOT.iterdir())
        if folder.is_dir() and (meta := get_skill_metadata(folder.name))
    ]

def select_skill(title: str, body: str = "") -> str | None:
    """Select at most ONE skill name using metadata and issue text without loading full SKILL.md bodies."""
    text = f"{title}\n{body}".casefold()

    # Read-only investigation questions do not need a coding skill
    if any(hint in text for hint in _INVESTIGATION_ONLY_HINTS) and not any(
        w in text for w in ("fix", "update", "change", "modify", "add", "implement")
    ):
        return None

    available = {m["name"]: m for m in list_skill_metadata()}
    if not available:
        return None

    best_skill: str | None = None
    best_score = 0

    for skill_name, meta in available.items():
         keywords = _SKILL_KEYWORDS.get(skill_name, ())
         desc_words = tuple(w for w in meta.get("description", "").casefold().split() if len(w) > 4)
         score = sum(2 for kw in keywords if kw in text) + sum(1 for dw in desc_words if dw in text)
         if score > best_score:
             best_score = score
             best_skill = skill_name

    # Default change-oriented issues to bug_fix if present, without loading any other skill
    if best_skill is None and "bug_fix" in available:
        return "bug_fix"
    return best_skill

def load_skill(name: str) -> str:
    """Return the body of <repository>/<name>/SKILL.md, or "" if it doesn't exist.

    Accepts a folder name ("bug_fix") or a classifier label ("bug_fix_skill").
    """
    if not name:
        return ""
    path = _skill_path(name)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text

"""Deterministic local retrieval over reviewed operational runbooks."""

from pathlib import Path
import re


RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"


def retrieve(findings: list[dict], limit: int = 3) -> list[dict]:
    """
    Retrieve operational runbooks matching the observed incident types.

    Only runbooks with matching issue tags are eligible.
    Lexical overlap is used to rank matching runbooks, not to
    introduce unrelated documents.

    This is deterministic retrieval, not embedding-based semantic RAG.
    """
    if limit <= 0 or not findings:
        return []

    issues = {
        str(f.get("issue", "")).strip()
        for f in findings
        if isinstance(f, dict)
    }
    issues.discard("")

    query = " ".join(
        str(f.get("evidence", ""))
        for f in findings
        if isinstance(f, dict)
    ).lower()

    terms = set(re.findall(r"[a-z]{4,}", query))

    ranked = []

    for path in sorted(RUNBOOK_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        if not lines:
            continue

        tags_line = next(
            (
                line
                for line in lines
                if line.startswith("Tags:")
            ),
            ""
        )

        tags = {
            tag.strip()
            for tag in tags_line.removeprefix("Tags:").split(",")
            if tag.strip()
        }

        matched_issues = issues & tags

        # Reject runbooks unrelated to the observed incident.
        if not matched_issues:
            continue

        lexical_score = len(
            terms & set(re.findall(r"[a-z]{4,}", content.lower()))
        )

        score = 10 * len(matched_issues) + lexical_score

        runbook = {
            "id": path.stem,
            "title": lines[0].lstrip("# ").strip(),
            "content": content,
            "source": f"runbooks/{path.name}",
        }

        ranked.append((score, path.name, runbook))

    ranked.sort(key=lambda item: (-item[0], item[1]))

    return [item[2] for item in ranked[:limit]]



"""Parse reviewed operational runbooks into stable RAG documents."""

import hashlib
from pathlib import Path


RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"


def parse_runbook(path: Path) -> dict:
    """Parse a reviewed Markdown runbook and preserve its provenance."""
    path = Path(path).resolve()
    root = RUNBOOK_DIR.resolve()

    if path.parent != root or path.suffix != ".md":
        raise ValueError("Runbook must be a Markdown file in the reviewed directory")

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"Runbook missing title: {path.name}")

    tag_lines = [line for line in lines if line.startswith("Tags:")]

    if len(tag_lines) != 1:
        raise ValueError(f"Runbook must have exactly one Tags field: {path.name}")

    tags = sorted({
        tag.strip()
        for tag in tag_lines[0].removeprefix("Tags:").split(",")
        if tag.strip()
    })

    if not tags:
        raise ValueError(f"Runbook missing issue tags: {path.name}")

    return {
        "document_id": f"runbook:{path.stem}",
        "source_path": f"runbooks/{path.name}",
        "title": lines[0][2:].strip(),
        "content": content,
        "issue_tags": tags,
        "content_sha256": hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest(),
    }


def load_runbooks() -> list[dict]:
    """Load reviewed runbooks in deterministic source-path order."""
    return [
        parse_runbook(path)
        for path in sorted(RUNBOOK_DIR.glob("*.md"))
    ]


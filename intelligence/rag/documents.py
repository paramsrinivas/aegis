
"""Parse reviewed operational runbooks into stable RAG documents."""

import hashlib
from pathlib import Path


RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"
RAG_RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "rag_runbooks"


def parse_runbook(path: Path) -> dict:
    """Parse an approved Markdown document and preserve provenance."""

    path = Path(path).resolve()

    allowed_roots = {
        RUNBOOK_DIR.resolve(),
        RAG_RUNBOOK_DIR.resolve(),
    }

    if path.parent not in allowed_roots or path.suffix != ".md":
        raise ValueError(
            "Runbook must be a Markdown file in a reviewed directory"
        )

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"Runbook missing title: {path.name}")

    tag_lines = [
        line for line in lines
        if line.startswith("Tags:")
    ]

    if len(tag_lines) != 1:
        raise ValueError(
            f"Runbook must have exactly one Tags field: {path.name}"
        )

    tags = sorted({
        tag.strip()
        for tag in tag_lines[0].removeprefix("Tags:").split(",")
        if tag.strip()
    })

    if not tags:
        raise ValueError(f"Runbook missing issue tags: {path.name}")

    return {
        "document_id": f"runbook:{path.stem}",
        "source_path": f"{path.parent.name}/{path.name}",
        "title": lines[0][2:].strip(),
        "content": content,
        "issue_tags": tags,
        "content_sha256": hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest(),
    }


def load_runbooks() -> list[dict]:
    """Load both reviewed corpora with unique document identifiers."""

    documents = [
        parse_runbook(path)
        for root in (RUNBOOK_DIR, RAG_RUNBOOK_DIR)
        for path in sorted(root.glob("*.md"))
    ]

    ids = [doc["document_id"] for doc in documents]

    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate runbook document identifiers")

    return documents


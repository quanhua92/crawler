"""Output formatters — json, jsonl, markdown, raw + media download."""

from __future__ import annotations

from app.models import CrawlResponse


def to_json(resp: CrawlResponse) -> str:
    return resp.model_dump_json(indent=2)


def to_jsonl(resp: CrawlResponse) -> str:
    items = resp.items or ([resp.item] if resp.item else [])
    return "\n".join(p.model_dump_json() for p in items)


def to_markdown(resp: CrawlResponse) -> str:
    """Render posts as readable markdown."""
    items = resp.items or ([resp.item] if resp.item else [])
    lines: list[str] = []
    for p in items:
        if p.title:
            lines.append(f"## {p.title}")
        if p.author:
            if p.created_at:
                lines.append(f"*@{p.author.username}* · `{p.created_at}`")
            else:
                lines.append(f"*@{p.author.username}*")
        lines.append("")
        lines.append(p.text)
        lines.append("")
        if p.url:
            lines.append(f"[source]({p.url})")
        for m in p.media:
            lines.append(f"![media]({m.url})")
        lines.append("\n---\n")
    return "\n".join(lines) if lines else "_no content_"


def render(resp: CrawlResponse, fmt: str) -> tuple[str, str]:
    """Returns (body, content_type) for the given format."""
    if fmt == "jsonl":
        return to_jsonl(resp), "application/jsonl"
    if fmt == "markdown":
        return to_markdown(resp), "text/markdown"
    if fmt == "raw":
        # Raw = just the first post's text/html
        item = (resp.items or [])[0] if resp.items else resp.item
        body = item.html or item.text if item else ""
        return body, "text/html" if item and item.html else "text/plain"
    return to_json(resp), "application/json"  # default json

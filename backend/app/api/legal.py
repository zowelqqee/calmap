"""Public legal pages linked from the app and the store listings.

The texts live in `app/legal/*.md`; operator details come from settings so the same
build serves any legal entity. A deliberately tiny Markdown subset is rendered
(headings, paragraphs, lists, tables, bold, links) to avoid a dependency.
"""

from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.core.config import settings

router = APIRouter(prefix="/legal", tags=["legal"])

LEGAL_DIR = Path(__file__).resolve().parent.parent / "legal"
EFFECTIVE_DATE = "14.10.2026"
PAGES = {
    "privacy": "privacy.md",
    "terms": "terms.md",
    "consent": "consent.md",
    "health-consent": "health-consent.md",
    "ai-consent": "ai-consent.md",
    "photo-consent": "photo-consent.md",
    "recommendations": "recommendations.md",
}


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"\[(.+?)\]\((/[^)\s]*)\)", r'<a href="\2">\1</a>', escaped)


def render_markdown(source: str) -> tuple[str, str]:
    """Return (title, html body) for the supported Markdown subset."""
    title = "Calmap"
    blocks: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    items: list[str] = []
    table: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_tag:
            blocks.append(
                f"<{list_tag}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{list_tag}>"
            )
            items.clear()
            list_tag = None

    def flush_table() -> None:
        if table:
            head, *rows = table
            html_rows = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rows
            )
            blocks.append(
                "<table><thead><tr>"
                + "".join(f"<th>{_inline(c)}</th>" for c in head)
                + f"</tr></thead><tbody>{html_rows}</tbody></table>"
            )
            table.clear()

    for raw in source.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("|"):
            flush_paragraph()
            flush_list()
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                table.append(cells)
            continue
        flush_table()
        bullet = re.match(r"^- (.*)", stripped)
        numbered = re.match(r"^\d+\. (.*)", stripped)
        if not stripped:
            flush_paragraph()
            flush_list()
        elif stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            title = stripped[2:]
            blocks.append(f"<h1>{_inline(title)}</h1>")
        elif stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif bullet or numbered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                flush_list()
                list_tag = tag
            items.append((bullet or numbered).group(1))
        elif list_tag and line.startswith("  "):
            items[-1] += " " + stripped
        else:
            flush_list()
            paragraph.append(stripped)
    flush_paragraph()
    flush_list()
    flush_table()
    return title, "\n".join(blocks)


@lru_cache
def _page(
    name: str,
    operator: str,
    email: str,
    ai_processor: str,
    ai_country: str,
    vision_processor: str,
    vision_country: str,
) -> str:
    source = (LEGAL_DIR / PAGES[name]).read_text(encoding="utf-8").format(
        operator=operator,
        email=email,
        effective_date=EFFECTIVE_DATE,
        ai_processor=ai_processor,
        ai_country=ai_country,
        vision_processor=vision_processor,
        vision_country=vision_country,
    )
    title, body = render_markdown(source)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{margin:0;background:#f7f4ee;color:#1f2a24;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:28px;line-height:1.25;color:#173d31}}h2{{font-size:20px;margin-top:32px;color:#173d31}}
a{{color:#2f6b4f}}li{{margin:4px 0}}
table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:15px}}
th,td{{border:1px solid #d9d2c3;padding:8px;text-align:left;vertical-align:top}}
th{{background:#efe9dc}}
</style></head><body><main>
{body}
</main></body></html>"""


@router.get("/{name}", response_class=HTMLResponse, include_in_schema=False)
async def legal_page(name: str) -> HTMLResponse:
    if name not in PAGES:
        raise HTTPException(404, "page not found")
    operator = settings.legal_operator_name or "оператор сервиса Calmap"
    email = settings.legal_contact_email or "адрес, указанный в карточке приложения"
    ai_processor = settings.assistant_processor_name or "провайдер AI-модели, указанный оператором"
    ai_country = settings.assistant_processor_country or "уточняется оператором"
    vision_processor = (
        settings.vision_processor_name
        or settings.assistant_processor_name
        or "сервис распознавания изображений, указанный оператором"
    )
    vision_country = (
        settings.vision_processor_country
        or settings.assistant_processor_country
        or "уточняется оператором"
    )
    return HTMLResponse(
        _page(name, operator, email, ai_processor, ai_country, vision_processor, vision_country)
    )


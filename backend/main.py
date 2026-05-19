"""DiffView — FastAPI backend.

Serves the single-page UI and exposes ``POST /api/diff``, which returns a flat
list of diff rows plus summary stats. Line-level diff uses
``difflib.SequenceMatcher``; replaced line pairs are re-diffed at the character
level so the frontend can render inline highlights.
"""

from __future__ import annotations

import html
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"

app = FastAPI(
    title="DiffView",
    description="GitHub-style file diff visualizer with character-level precision.",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DiffRequest(BaseModel):
    old_content: str = Field(default="", description="Original file content")
    new_content: str = Field(default="", description="New file content")
    context_lines: int = Field(
        default=3, ge=0, le=200,
        description="Unchanged lines of context shown around each change",
    )


class DiffLine(BaseModel):
    type: str  # "add" | "del" | "ctx"
    text: str
    ln_old: int | None = None
    ln_new: int | None = None
    # Pre-rendered HTML with inline <mark> spans — only set for replace pairs.
    char_old: str | None = None
    char_new: str | None = None


class DiffStats(BaseModel):
    added: int
    removed: int
    changed: int
    old_lines: int
    new_lines: int
    similarity: float


class DiffResponse(BaseModel):
    lines: list[DiffLine]
    stats: DiffStats


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------


def _split_lines(content: str) -> list[str]:
    # splitlines() strips terminators, which is what we want for row-by-row display.
    return content.splitlines() if content else []


def _char_diff_html(old: str, new: str) -> tuple[str, str]:
    """HTML-escape ``old``/``new`` and wrap differing runs in <mark> spans."""
    sm = SequenceMatcher(a=old, b=new, autojunk=False)
    old_parts: list[str] = []
    new_parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a_seg = html.escape(old[i1:i2])
        b_seg = html.escape(new[j1:j2])
        if tag == "equal":
            old_parts.append(a_seg)
            new_parts.append(b_seg)
        elif tag == "delete":
            old_parts.append(f'<mark class="char-del">{a_seg}</mark>')
        elif tag == "insert":
            new_parts.append(f'<mark class="char-add">{b_seg}</mark>')
        elif tag == "replace":
            old_parts.append(f'<mark class="char-del">{a_seg}</mark>')
            new_parts.append(f'<mark class="char-add">{b_seg}</mark>')
    return "".join(old_parts), "".join(new_parts)


def _build_diff(old: str, new: str, context_lines: int) -> DiffResponse:
    old_lines = _split_lines(old)
    new_lines = _split_lines(new)

    sm = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    similarity = round(sm.ratio() * 100, 1)

    added = removed = changed = 0
    out: list[DiffLine] = []

    groups = list(sm.get_grouped_opcodes(n=context_lines))

    # No groups => files identical (or both empty). Surface everything as context
    # so the UI can still render the file rather than showing a blank pane.
    if not groups:
        for idx, line in enumerate(old_lines, start=1):
            out.append(DiffLine(type="ctx", text=line, ln_old=idx, ln_new=idx))
        return DiffResponse(
            lines=out,
            stats=DiffStats(
                added=0, removed=0, changed=0,
                old_lines=len(old_lines), new_lines=len(new_lines),
                similarity=similarity,
            ),
        )

    for group in groups:
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for k in range(i2 - i1):
                    out.append(DiffLine(
                        type="ctx",
                        text=old_lines[i1 + k],
                        ln_old=i1 + k + 1,
                        ln_new=j1 + k + 1,
                    ))
            elif tag == "delete":
                for k in range(i2 - i1):
                    removed += 1
                    out.append(DiffLine(
                        type="del",
                        text=old_lines[i1 + k],
                        ln_old=i1 + k + 1,
                    ))
            elif tag == "insert":
                for k in range(j2 - j1):
                    added += 1
                    out.append(DiffLine(
                        type="add",
                        text=new_lines[j1 + k],
                        ln_new=j1 + k + 1,
                    ))
            elif tag == "replace":
                old_chunk = old_lines[i1:i2]
                new_chunk = new_lines[j1:j2]
                pair_count = min(len(old_chunk), len(new_chunk))
                # Paired replacements get char-level highlights.
                for k in range(pair_count):
                    changed += 1
                    char_old, char_new = _char_diff_html(old_chunk[k], new_chunk[k])
                    out.append(DiffLine(
                        type="del",
                        text=old_chunk[k],
                        ln_old=i1 + k + 1,
                        char_old=char_old,
                    ))
                    out.append(DiffLine(
                        type="add",
                        text=new_chunk[k],
                        ln_new=j1 + k + 1,
                        char_new=char_new,
                    ))
                # Unpaired remainder => plain add/del rows (no partner to compare).
                for k in range(pair_count, len(old_chunk)):
                    removed += 1
                    out.append(DiffLine(
                        type="del",
                        text=old_chunk[k],
                        ln_old=i1 + k + 1,
                    ))
                for k in range(pair_count, len(new_chunk)):
                    added += 1
                    out.append(DiffLine(
                        type="add",
                        text=new_chunk[k],
                        ln_new=j1 + k + 1,
                    ))

    return DiffResponse(
        lines=out,
        stats=DiffStats(
            added=added,
            removed=removed,
            changed=changed,
            old_lines=len(old_lines),
            new_lines=len(new_lines),
            similarity=similarity,
        ),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/diff", response_model=DiffResponse)
async def diff(payload: DiffRequest) -> DiffResponse:
    return _build_diff(payload.old_content, payload.new_content, payload.context_lines)

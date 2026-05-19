"""DiffView — FastAPI backend.

Serves the single-page UI and exposes ``POST /api/diff``, which returns a flat
list of diff rows plus summary stats. Line-level diff uses
``difflib.SequenceMatcher``; replaced line pairs are re-diffed at the character
level so the frontend can render inline highlights.
"""

from __future__ import annotations

import html
import threading
from contextlib import asynccontextmanager
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"
WATCHED_DIR = BASE_DIR / "watched"
WATCHED_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# File watcher
#
# Tracks files directly inside ``watched/``. When a file changes, we record
# {old_content: <previous snapshot>, new_content: <current contents>} and
# advance the baseline so the next change compares against this version.
# ---------------------------------------------------------------------------


_watch_lock = threading.Lock()
_baseline: dict[str, str] = {}
_changes: dict[str, dict[str, str]] = {}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _is_user_file(name: str) -> bool:
    # Skip dotfiles and the common editor / atomic-save temp suffixes
    # (VS Code writes ``foo.html.tmp.<pid>.<rand>`` during save, vim writes
    # ``.foo.swp``, many editors leave a trailing ``~``).
    if name.startswith(".") or name.endswith("~"):
        return False
    lowered = name.lower()
    bad_suffixes = (".swp", ".swo", ".bak", ".part", ".crdownload")
    if lowered.endswith(bad_suffixes):
        return False
    if ".tmp." in lowered or lowered.endswith(".tmp"):
        return False
    return True


def _seed_baseline() -> None:
    with _watch_lock:
        _baseline.clear()
        _changes.clear()
        for entry in WATCHED_DIR.iterdir():
            if entry.is_file() and _is_user_file(entry.name):
                content = _read_text(entry)
                if content is not None:
                    _baseline[entry.name] = content


class _WatchedHandler(FileSystemEventHandler):
    def _record(self, src_path: str) -> None:
        path = Path(src_path)
        if not path.is_file():
            return
        try:
            rel = path.relative_to(WATCHED_DIR)
        except ValueError:
            return
        # Ignore nested files — only watch the top level.
        if len(rel.parts) != 1:
            return
        if not _is_user_file(path.name):
            return
        new_content = _read_text(path)
        if new_content is None:
            return
        name = rel.name
        with _watch_lock:
            old = _baseline.get(name, "")
            # Editors fire spurious modify events on save; skip no-ops.
            if old == new_content:
                return
            _changes[name] = {"old_content": old, "new_content": new_content}
            _baseline[name] = new_content

    def on_modified(self, event):  # noqa: D401
        if not event.is_directory:
            self._record(event.src_path)

    def on_created(self, event):  # noqa: D401
        if not event.is_directory:
            self._record(event.src_path)

    def on_moved(self, event):  # noqa: D401
        # Atomic saves arrive as a move from a temp path onto the target.
        if not event.is_directory:
            self._record(event.dest_path)

    # NOTE: on_deleted is intentionally not handled. Many editors save
    # atomically (write temp → delete original → rename temp), so a delete
    # event can fire just before the file reappears with new contents. If we
    # popped the baseline on delete, that follow-up create would compare
    # against "" and report the entire file as added. Letting a stale entry
    # linger after a true delete is the lesser evil.


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_baseline()
    observer = Observer()
    observer.schedule(_WatchedHandler(), str(WATCHED_DIR), recursive=False)
    observer.start()
    try:
        yield
    finally:
        observer.stop()
        observer.join(timeout=2)


app = FastAPI(
    title="DiffView",
    description="GitHub-style file diff visualizer with character-level precision.",
    version="1.0.0",
    lifespan=lifespan,
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
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/diff", response_model=DiffResponse)
async def diff(payload: DiffRequest) -> DiffResponse:
    return _build_diff(payload.old_content, payload.new_content, payload.context_lines)


@app.get("/api/watched")
async def list_watched() -> dict:
    with _watch_lock:
        return {"files": sorted(_changes.keys())}


@app.get("/api/watched/{filename}")
async def get_watched(filename: str) -> dict:
    with _watch_lock:
        change = _changes.get(filename)
    if change is None:
        raise HTTPException(status_code=404, detail=f"No tracked changes for '{filename}'")
    return {"filename": filename, **change}

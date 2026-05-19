# DiffView

A full-stack file diff visualizer built with **Python (FastAPI)** and **vanilla JS**. Paste two versions of any text file — HTML, Mermaid diagrams, Markdown, code — and get a GitHub-style diff with character-level precision. Or drop a file into a watched folder and pull in the latest change with one click.

Originally built to track changes Claude makes to architecture diagrams and flowcharts during iterative editing sessions.

---

## Features

- **Three view modes** — toggle between **Unified** (GitHub-style), **Split** (side-by-side), and **Document** (prose with track-changes-style word-level highlights)
- **Character-level highlighting** — within changed lines, shows exactly which characters were added or removed (not just the whole line)
- **Word-level diff (Document mode)** — strips HTML tags, runs an LCS word diff entirely in the browser, and renders the result as flowing prose with red strikethrough deletions and green additions
- **File upload** — pick a `.html`/`.md`/`.txt`/`.js`/`.css`/`.mermaid` file from disk to populate either pane
- **File watcher** — drop files into `watched/`, edit them in any editor, and click **Reload & Compare** to diff the latest version against the previous one
- **Similarity score** — percentage similarity between the two versions using Python's `difflib.SequenceMatcher`
- **Configurable context** — control how many unchanged lines are shown around each change
- **Stats bar** — instant summary of lines added, removed, changed, and total line counts
- **REST API** — `/api/diff` and `/api/watched` endpoints return structured JSON, usable from any client
- **Keyboard shortcut** — `Cmd/Ctrl + Enter` to compare
- **Zero dependencies on the frontend** — pure HTML, CSS, and vanilla JS

---

## Architecture

```
DiffView/
├── backend/
│   └── main.py              # FastAPI app — diff engine, file watcher, API routes
├── frontend/
│   ├── templates/
│   │   └── index.html       # Single-page UI: editors, toolbar, stats, diff area
│   └── static/
│       ├── css/style.css    # Dark theme, monospace diff table, document view
│       └── js/app.js        # Fetches API, renders unified/split/document views
├── watched/
│   └── example.html         # Sample file the watcher tracks
├── requirements.txt         # fastapi, uvicorn[standard], jinja2, watchdog
└── README.md
```

### How the diff works

1. The browser sends both file contents to `POST /api/diff`
2. The Python backend splits content into lines and runs `difflib.SequenceMatcher` to compute a line-level diff (LCS-based)
3. For lines that were *replaced* (not just added or deleted), a second character-level `SequenceMatcher` pass computes inline char highlights
4. The API returns a flat list of `DiffLine` objects with type (`add`, `del`, `ctx`), line numbers, and optional pre-rendered HTML for char highlights
5. The frontend renders the lines into a `<table>` — unified or split — with CSS-only coloring

### Document view (client-side word diff)

When **Document** is selected, the frontend skips the API entirely:

1. Both inputs are stripped of HTML tags, scripts, styles, and common entities are decoded
2. Each side is tokenized as alternating word / whitespace tokens (`/\S+|\s+/g`)
3. A JavaScript LCS implementation produces a list of `eq` / `add` / `del` ops
4. Consecutive same-type ops are collapsed into one `<span>` so multi-word changes read as a single phrase, then dropped into a prose-style panel

Example: `"I went to the zoo"` → `"Preetam went to the zoo"` renders as ~~I~~ Preetam went to the zoo, with red strikethrough on `I` and a green background on `Preetam`.

### File watcher

`watched/` is monitored by `watchdog`. When a file there changes, the backend stores `{old_content, new_content}` in memory keyed by filename — `old_content` is the previous snapshot, `new_content` is the latest. Atomic saves (write-temp → delete → rename) are handled so the baseline survives editor save cycles. Click **Reload & Compare** in the UI to pull the latest change into the editors and run a diff automatically.

### API

```
POST /api/diff
Content-Type: application/json

{
  "old_content": "...",
  "new_content": "...",
  "context_lines": 3
}
```

**Response:**
```json
{
  "lines": [
    {
      "type": "del",
      "text": "  <title>System Architecture</title>",
      "ln_old": 3,
      "char_old": "  &lt;title&gt;System Architecture&lt;/title&gt;",
      "char_new": "  &lt;title&gt;System Architecture <mark class=\"char-add\">v2</mark>&lt;/title&gt;"
    }
  ],
  "stats": {
    "added": 5, "removed": 2, "changed": 3,
    "old_lines": 14, "new_lines": 17, "similarity": 83.6
  }
}
```

```
GET /api/watched
→ { "files": ["example.html", ...] }

GET /api/watched/{filename}
→ { "filename": "...", "old_content": "...", "new_content": "..." }
```

---

## Usage

### 1. Clone & install

```bash
git clone https://github.com/pdonepud/DiffView.git
cd DiffView
pip install -r requirements.txt
```

### 2. Run

```bash
uvicorn backend.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### 3. Use

- **Paste or upload** two files into the left/right panels
- Click **Compare** (or press `Cmd/Ctrl + Enter`)
- Switch between **Unified**, **Split**, and **Document** views — no re-fetch on toggle
- Adjust **Context** to show more or fewer unchanged lines
- Or: edit a file in `watched/` and click **Reload & Compare** to diff the previous-vs-current snapshot

### 4. API-only usage

```bash
curl -X POST http://localhost:8000/api/diff \
  -H "Content-Type: application/json" \
  -d '{
    "old_content": "hello\nworld",
    "new_content": "hello\nearth"
  }'
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Diff engine | Python `difflib` (SequenceMatcher, LCS) |
| File watching | `watchdog` |
| Templating | Jinja2 |
| Frontend | HTML5, CSS3 (custom properties), Vanilla JS |

No database. No auth. No frontend build step. Just Python and a browser.

---

## Development

```bash
# Run with auto-reload
uvicorn backend.main:app --reload --port 8000
```

The API is fully typed with Pydantic models, so you get automatic docs at:
- [http://localhost:8000/docs](http://localhost:8000/docs) — Swagger UI
- [http://localhost:8000/redoc](http://localhost:8000/redoc) — ReDoc

---

## License

MIT License — see [LICENSE](LICENSE) for details.

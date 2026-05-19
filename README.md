# DiffView

A full-stack file diff visualizer built with **Python (FastAPI)** and **vanilla JS**. Paste two versions of any text file — HTML, Mermaid diagrams, Markdown, code — and get a GitHub-style diff with character-level precision.

Originally built to track changes Claude makes to architecture diagrams and flowcharts during iterative editing sessions.

---

## Features

- **Unified & split view** — toggle between GitHub-style unified diff and side-by-side split view
- **Character-level highlighting** — within changed lines, shows exactly which characters were added or removed (not just the whole line)
- **Similarity score** — percentage similarity between the two versions using Python's `difflib.SequenceMatcher`
- **Configurable context** — control how many unchanged lines are shown around each change
- **Stats bar** — instant summary of lines added, removed, changed, and total line counts
- **REST API** — `/api/diff` endpoint returns structured JSON, usable from any client
- **Keyboard shortcut** — `Cmd/Ctrl + Enter` to compare
- **Zero dependencies on the frontend** — pure HTML, CSS, and vanilla JS

---

## Architecture

```
diffview/
├── backend/
│   └── main.py              # FastAPI app — diff logic + API routes
├── frontend/
│   ├── templates/
│   │   └── index.html       # Jinja2 HTML template
│   └── static/
│       ├── css/style.css    # All styles (dark theme, diff colors)
│       └── js/app.js        # Fetch API calls + diff rendering
├── requirements.txt
└── README.md
```

### How the diff works

1. The browser sends both file contents to `POST /api/diff`
2. The Python backend splits content into lines and runs `difflib.SequenceMatcher` to compute a line-level diff (LCS-based)
3. For lines that were *replaced* (not just added or deleted), a second character-level `SequenceMatcher` pass computes inline char highlights
4. The API returns a flat list of `DiffLine` objects with type (`add`, `del`, `ctx`), line numbers, and optional pre-rendered HTML for char highlights
5. The frontend renders the lines into a `<table>` — unified or split — with CSS-only coloring

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
      "ln_new": null,
      "char_old": "  &lt;title&gt;System Architecture&lt;/title&gt;",
      "char_new": "  &lt;title&gt;System Architecture <mark class=\"char-add\">v2</mark>&lt;/title&gt;"
    }
  ],
  "stats": {
    "added": 5,
    "removed": 2,
    "changed": 3,
    "old_lines": 14,
    "new_lines": 17,
    "similarity": 83.6
  }
}
```

---

## Usage

### 1. Clone & install

```bash
git clone https://github.com/pdonepud/diffview.git
cd diffview
pip install -r requirements.txt
```

### 2. Run

```bash
uvicorn backend.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### 3. Use

1. Paste your **original file** in the left panel
2. Paste the **updated file** in the right panel
3. Click **Compare** (or press `Cmd/Ctrl + Enter`)
4. Toggle between **Unified** and **Split** view
5. Adjust the **Context** number to show more or fewer unchanged lines

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
| Templating | Jinja2 |
| Frontend | HTML5, CSS3 (custom properties), Vanilla JS |
| Fonts | Space Mono, DM Sans (Google Fonts) |

No database. No auth. No build step. Just Python and a browser.

---

## Development

```bash
# Install dev dependencies (optional)
pip install httpx pytest

# Run tests
pytest

# Run with auto-reload
uvicorn backend.main:app --reload --port 8000
```

The API is fully typed with Pydantic models, so you get automatic docs at:
- [http://localhost:8000/docs](http://localhost:8000/docs) — Swagger UI
- [http://localhost:8000/redoc](http://localhost:8000/redoc) — ReDoc

---

## License

MIT License — see [LICENSE](LICENSE) for details.

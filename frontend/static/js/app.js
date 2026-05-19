(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const els = {
    oldContent: $("old-content"),
    newContent: $("new-content"),
    oldFile: $("old-file"),
    newFile: $("new-file"),
    compareBtn: $("compare-btn"),
    loadExampleBtn: $("load-example-btn"),
    reloadCompareBtn: $("reload-compare-btn"),
    watchedSelect: $("watched-select"),
    contextLines: $("context-lines"),
    statsBar: $("stats-bar"),
    statAdded: $("stat-added"),
    statRemoved: $("stat-removed"),
    statChanged: $("stat-changed"),
    statSimilarity: $("stat-similarity"),
    diffOutput: $("diff-output"),
    emptyState: $("empty-state"),
  };

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  const escapeHtml = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const lnCell = (n) => `<td class="ln">${n ?? ""}</td>`;
  const signCell = (s) => `<td class="sign">${s}</td>`;
  const codeCell = (html, extraClass = "") =>
    `<td class="code${extraClass ? " " + extraClass : ""}">${html}</td>`;

  // Use server-provided char-level HTML if present (already escaped + marked),
  // otherwise escape the raw text.
  const renderCode = (line, side /* "old" | "new" */) => {
    if (side === "old" && line.char_old != null) return line.char_old;
    if (side === "new" && line.char_new != null) return line.char_new;
    return escapeHtml(line.text);
  };

  const getViewMode = () => {
    const checked = document.querySelector('input[name="view-mode"]:checked');
    return checked ? checked.value : "unified";
  };

  // ---------------------------------------------------------------------------
  // Document-mode helpers (word-level diff on plain text)
  // ---------------------------------------------------------------------------

  // Strip HTML tags and decode common entities. Block-level closers become
  // newlines so paragraphs don't collapse into one long run.
  const stripHtml = (input) =>
    input
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
      .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, "")
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/(p|div|h[1-6]|li|tr|blockquote|pre|section|article|header|footer)>/gi, "\n")
      .replace(/<[^>]+>/g, "")
      .replace(/&nbsp;/g, " ")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n");

  // Split into alternating word / whitespace tokens so whitespace survives diff.
  const tokenizeWords = (text) => text.match(/\S+|\s+/g) || [];

  // LCS-based diff returning ordered ops: { type: 'eq'|'add'|'del', word }.
  const wordDiff = (a, b) => {
    const m = a.length;
    const n = b.length;
    // Rows of length n+1; use plain Array for simplicity (typical inputs modest).
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        dp[i][j] = a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1] + 1
          : Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
    const ops = [];
    let i = m;
    let j = n;
    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
        ops.push({ type: "eq", word: a[i - 1] });
        i--; j--;
      } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
        ops.push({ type: "add", word: b[j - 1] });
        j--;
      } else {
        ops.push({ type: "del", word: a[i - 1] });
        i--;
      }
    }
    ops.reverse();
    return ops;
  };

  // Build the document-view HTML by collapsing consecutive same-type ops
  // into a single span so multi-word runs read as one phrase.
  const renderDocument = (oldRaw, newRaw) => {
    const oldText = stripHtml(oldRaw);
    const newText = stripHtml(newRaw);
    const a = tokenizeWords(oldText);
    const b = tokenizeWords(newText);

    if (a.length === 0 && b.length === 0) {
      return `<div class="document-view"><div class="document-view__empty">No text to compare.</div></div>`;
    }

    const ops = wordDiff(a, b);

    let html = '<div class="document-view">';
    let added = 0;
    let removed = 0;
    let kept = 0;
    let idx = 0;
    while (idx < ops.length) {
      const type = ops[idx].type;
      let chunk = "";
      while (idx < ops.length && ops[idx].type === type) {
        const w = ops[idx].word;
        chunk += w;
        // Count words only, not pure whitespace tokens.
        if (/\S/.test(w)) {
          if (type === "add") added++;
          else if (type === "del") removed++;
          else kept++;
        }
        idx++;
      }
      const escaped = escapeHtml(chunk);
      if (type === "eq") html += escaped;
      else html += `<span class="word-${type}">${escaped}</span>`;
    }
    html += "</div>";

    const oldWords = a.filter((t) => /\S/.test(t)).length;
    const newWords = b.filter((t) => /\S/.test(t)).length;
    const denom = oldWords + newWords;
    const similarity = denom === 0 ? 100 : Math.round((2 * kept * 1000) / denom) / 10;

    return {
      html,
      stats: {
        added,
        removed,
        changed: 0,
        similarity,
      },
    };
  };

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  const renderUnified = (lines) => {
    const rows = [];
    let prevOld = null;
    let prevNew = null;

    for (const line of lines) {
      // Detect a context gap and emit a hunk separator.
      if (
        line.type === "ctx" &&
        prevOld != null &&
        line.ln_old != null &&
        line.ln_old > prevOld + 1
      ) {
        rows.push(
          `<tr class="hunk"><td colspan="4">@@ -${line.ln_old} +${line.ln_new} @@</td></tr>`
        );
      }

      if (line.type === "ctx") {
        rows.push(
          `<tr class="ctx">${lnCell(line.ln_old)}${lnCell(line.ln_new)}${signCell(" ")}${codeCell(escapeHtml(line.text))}</tr>`
        );
        prevOld = line.ln_old;
        prevNew = line.ln_new;
      } else if (line.type === "del") {
        rows.push(
          `<tr class="del">${lnCell(line.ln_old)}${lnCell("")}${signCell("-")}${codeCell(renderCode(line, "old"))}</tr>`
        );
        prevOld = line.ln_old;
      } else if (line.type === "add") {
        rows.push(
          `<tr class="add">${lnCell("")}${lnCell(line.ln_new)}${signCell("+")}${codeCell(renderCode(line, "new"))}</tr>`
        );
        prevNew = line.ln_new;
      }
    }

    return `<table>${rows.join("")}</table>`;
  };

  const renderSplit = (lines) => {
    const rows = [];
    let pendingDel = [];
    let pendingAdd = [];
    let prevOld = null;

    const flushPending = () => {
      const n = Math.max(pendingDel.length, pendingAdd.length);
      for (let i = 0; i < n; i++) {
        const d = pendingDel[i];
        const a = pendingAdd[i];

        const leftLn = d ? d.ln_old : "";
        const leftSign = d ? "-" : " ";
        const leftCode = d ? renderCode(d, "old") : "";
        const leftCls = d ? "del" : "ctx";

        const rightLn = a ? a.ln_new : "";
        const rightSign = a ? "+" : " ";
        const rightCode = a ? renderCode(a, "new") : "";
        const rightCls = a ? "add" : "ctx";

        rows.push(
          `<tr class="${leftCls === rightCls ? leftCls : "mixed"}">` +
            `<td class="ln">${leftLn}</td>` +
            `<td class="sign">${leftSign}</td>` +
            `<td class="code pane-old${d ? " del-cell" : ""}">${leftCode}</td>` +
            `<td class="ln">${rightLn}</td>` +
            `<td class="sign">${rightSign}</td>` +
            `<td class="code pane-new${a ? " add-cell" : ""}">${rightCode}</td>` +
            `</tr>`
        );
      }
      pendingDel = [];
      pendingAdd = [];
    };

    for (const line of lines) {
      if (line.type === "ctx") {
        flushPending();

        if (
          prevOld != null &&
          line.ln_old != null &&
          line.ln_old > prevOld + 1
        ) {
          rows.push(
            `<tr class="hunk"><td colspan="6">@@ -${line.ln_old} +${line.ln_new} @@</td></tr>`
          );
        }

        const html = escapeHtml(line.text);
        rows.push(
          `<tr class="ctx">` +
            `<td class="ln">${line.ln_old}</td>` +
            `<td class="sign"> </td>` +
            `<td class="code pane-old">${html}</td>` +
            `<td class="ln">${line.ln_new}</td>` +
            `<td class="sign"> </td>` +
            `<td class="code pane-new">${html}</td>` +
            `</tr>`
        );
        prevOld = line.ln_old;
      } else if (line.type === "del") {
        pendingDel.push(line);
      } else if (line.type === "add") {
        pendingAdd.push(line);
      }
    }
    flushPending();

    return `<table>${rows.join("")}</table>`;
  };

  // ---------------------------------------------------------------------------
  // State updates
  // ---------------------------------------------------------------------------

  const updateStats = (stats) => {
    els.statAdded.textContent = stats.added;
    els.statRemoved.textContent = stats.removed;
    els.statChanged.textContent = stats.changed;
    els.statSimilarity.textContent = `${stats.similarity}%`;
  };

  const showResults = (data) => {
    const { lines, stats } = data;
    updateStats(stats);

    const mode = getViewMode();
    els.diffOutput.classList.toggle("split", mode === "split");
    els.diffOutput.classList.toggle("document", false);
    els.diffOutput.innerHTML =
      mode === "split" ? renderSplit(lines) : renderUnified(lines);

    els.statsBar.hidden = false;
    els.diffOutput.hidden = false;
    els.emptyState.hidden = true;
  };

  const showDocument = () => {
    const result = renderDocument(els.oldContent.value, els.newContent.value);
    // Empty inputs → render the empty placeholder and bail without stats.
    if (typeof result === "string") {
      els.diffOutput.classList.remove("split");
      els.diffOutput.classList.add("document");
      els.diffOutput.innerHTML = result;
      els.diffOutput.hidden = false;
      els.statsBar.hidden = true;
      els.emptyState.hidden = true;
      return;
    }
    updateStats(result.stats);
    els.diffOutput.classList.remove("split");
    els.diffOutput.classList.add("document");
    els.diffOutput.innerHTML = result.html;
    els.statsBar.hidden = false;
    els.diffOutput.hidden = false;
    els.emptyState.hidden = true;
  };

  const showEmpty = () => {
    els.statsBar.hidden = true;
    els.diffOutput.hidden = true;
    els.diffOutput.innerHTML = "";
    els.emptyState.hidden = false;
  };

  // Cache the last response so changing view mode doesn't require re-fetching.
  let lastResponse = null;

  // ---------------------------------------------------------------------------
  // API call
  // ---------------------------------------------------------------------------

  const runCompare = async () => {
    // Document mode is purely client-side — no API round-trip needed.
    if (getViewMode() === "document") {
      showDocument();
      return;
    }

    const payload = {
      old_content: els.oldContent.value,
      new_content: els.newContent.value,
      context_lines: Math.max(
        0,
        Math.min(200, parseInt(els.contextLines.value, 10) || 0)
      ),
    };

    els.compareBtn.disabled = true;
    const originalLabel = els.compareBtn.textContent;
    els.compareBtn.textContent = "Comparing…";

    try {
      const res = await fetch("/api/diff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Server returned ${res.status}: ${text || res.statusText}`);
      }
      const data = await res.json();
      lastResponse = data;
      showResults(data);
    } catch (err) {
      console.error(err);
      alert(`Diff failed: ${err.message}`);
    } finally {
      els.compareBtn.disabled = false;
      els.compareBtn.textContent = originalLabel;
    }
  };

  // ---------------------------------------------------------------------------
  // Example loader
  // ---------------------------------------------------------------------------

  const EXAMPLE_OLD = `<!DOCTYPE html>
<html>
<head>
  <title>My Site</title>
</head>
<body>
  <h1>Hello</h1>
  <p>Welcome to my site.</p>
  <ul>
    <li>Home</li>
    <li>About</li>
  </ul>
</body>
</html>
`;

  const EXAMPLE_NEW = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>My Personal Site</title>
</head>
<body>
  <h1>Hello, world!</h1>
  <p>Welcome to my personal site.</p>
  <ul>
    <li>Home</li>
    <li>About</li>
    <li>Contact</li>
  </ul>
</body>
</html>
`;

  const loadExample = () => {
    els.oldContent.value = EXAMPLE_OLD;
    els.newContent.value = EXAMPLE_NEW;
    runCompare();
  };

  // ---------------------------------------------------------------------------
  // Event wiring
  // ---------------------------------------------------------------------------

  els.compareBtn.addEventListener("click", runCompare);
  els.loadExampleBtn.addEventListener("click", loadExample);

  // -------------------------------------------------------------------------
  // Reload & Compare — pull the latest tracked change from watched/
  // -------------------------------------------------------------------------

  const loadWatchedFile = async (filename) => {
    const res = await fetch(`/api/watched/${encodeURIComponent(filename)}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Server returned ${res.status}: ${text || res.statusText}`);
    }
    const data = await res.json();
    els.oldContent.value = data.old_content;
    els.newContent.value = data.new_content;
    await runCompare();
  };

  const populateWatchedSelect = (files) => {
    const sel = els.watchedSelect;
    sel.innerHTML = '<option value="">Pick a watched file…</option>' +
      files.map((f) => `<option value="${escapeHtml(f)}">${escapeHtml(f)}</option>`).join("");
    sel.value = "";
    sel.hidden = false;
  };

  const onReloadCompare = async () => {
    els.reloadCompareBtn.disabled = true;
    try {
      const res = await fetch("/api/watched");
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const { files } = await res.json();
      if (!files || files.length === 0) {
        alert("No tracked changes yet. Modify a file inside watched/ and try again.");
        els.watchedSelect.hidden = true;
        return;
      }
      if (files.length === 1) {
        els.watchedSelect.hidden = true;
        await loadWatchedFile(files[0]);
        return;
      }
      populateWatchedSelect(files);
      els.watchedSelect.focus();
    } catch (err) {
      console.error(err);
      alert(`Reload failed: ${err.message}`);
    } finally {
      els.reloadCompareBtn.disabled = false;
    }
  };

  els.reloadCompareBtn.addEventListener("click", onReloadCompare);
  els.watchedSelect.addEventListener("change", async () => {
    const filename = els.watchedSelect.value;
    if (!filename) return;
    try {
      await loadWatchedFile(filename);
    } catch (err) {
      console.error(err);
      alert(`Failed to load ${filename}: ${err.message}`);
    }
  });

  // File upload → populate textarea
  const wireFileUpload = (input, textarea) => {
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        textarea.value = typeof reader.result === "string" ? reader.result : "";
      };
      reader.onerror = () => alert(`Could not read ${file.name}: ${reader.error}`);
      reader.readAsText(file);
      // Reset so picking the same file twice still fires "change".
      input.value = "";
    });
  };
  wireFileUpload(els.oldFile, els.oldContent);
  wireFileUpload(els.newFile, els.newContent);

  // Re-render on view-mode toggle without re-fetching.
  document.querySelectorAll('input[name="view-mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const mode = getViewMode();
      if (mode === "document") {
        showDocument();
      } else if (lastResponse) {
        showResults(lastResponse);
      }
    });
  });

  // Cmd/Ctrl+Enter to compare from anywhere.
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      runCompare();
    }
  });

  // Initial state
  showEmpty();
})();

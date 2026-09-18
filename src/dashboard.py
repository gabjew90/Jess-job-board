"""Generate the static dashboard (docs/index.html) from state, for GitHub Pages."""
import html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

REPO = "gabjew90/Jess-job-board"


def _feedback_body(rec: dict) -> str:
    """Pre-fill the feedback issue with how this posting was scored, so the
    owner reacts to the model's actual reasoning."""
    fp = rec.get("scoring_fingerprint") or {}
    lines = [
        "How this was scored:",
        f"- Band: {rec.get('band', rec.get('score', '?'))}"
        f" (seniority_match: {rec.get('seniority_match', '?')})",
        f"- Rationale: {rec.get('rationale') or '(none recorded)'}",
    ]
    if fp:
        lines.append(f"- By: {fp.get('model', '?')} · rubric {fp.get('rubric', '?')}"
                     f" · {fp.get('at', '?')}")
    lines += [
        "",
        "What's right or wrong with this reasoning? Write below — your notes",
        "feed directly into future scoring:",
        "",
        "",
        "---",
        "To hide this posting entirely, include a line: Action: hide",
    ]
    return "\n".join(lines)

OUT = Path("docs/index.html")

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Watcher</title>
<style>
  :root {{ color-scheme: light dark; --border: #8884; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 72rem; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; }} .meta {{ opacity: .7; font-size: .85rem; }}
  input {{ padding: .4rem .6rem; margin: .8rem 0; width: 16rem; max-width: 100%; }}
  .tablewrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--border); }}
  th {{ cursor: pointer; white-space: nowrap; user-select: none; }}
  tr.priority td:first-child::before {{ content: "⭐ "; }}
  tr.closed {{ opacity: .45; }}
  tr.closed td:first-child a {{ text-decoration: line-through; }}
  label {{ font-size: .85rem; margin-left: .8rem; user-select: none; }}
  a {{ color: inherit; }}
</style>
</head>
<body>
<h1>Job Watcher</h1>
<p class="meta">{active_count} active · {closed_count} closed · last refresh: <span id="upd" data-ts="{generated_iso}">{generated} UTC</span></p>
<input id="q" type="search" placeholder="Filter…" oninput="applyVis()"><label><input id="sc" type="checkbox" onchange="applyVis()"> show closed</label>
<div class="tablewrap">
<table id="t">
<thead><tr>
  <th onclick="sortBy(0)">Title</th><th onclick="sortBy(1)">Company</th>
  <th onclick="sortBy(2)">Location</th><th onclick="sortBy(3)">Mode</th>
  <th onclick="sortBy(4)">Pay</th><th onclick="sortBy(5)">Posted</th>
  <th onclick="sortBy(6)">First seen</th><th onclick="sortBy(7, true)">Fit</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<h2 style="font-size:1.1rem;margin-top:2rem">Source health</h2>
<div class="tablewrap">
<table>
<thead><tr><th>Source</th><th>Status</th><th>Results</th><th>Last results</th><th>Error</th></tr></thead>
<tbody>
{health_rows}
</tbody>
</table>
</div>
<script>
let dir = -1, col = 6;
function sortBy(c, numeric) {{
  dir = (c === col) ? -dir : (numeric ? -1 : 1); col = c;
  const tb = document.querySelector("#t tbody");
  [...tb.rows].sort((a, b) => {{
    const val = (r) => numeric ? parseFloat(r.cells[c].dataset.s ?? r.cells[c].innerText) || -1
                               : r.cells[c].innerText;
    return numeric ? dir * (val(a) - val(b)) : dir * val(a).localeCompare(val(b));
  }}).forEach(r => tb.appendChild(r));
}}
function applyVis() {{
  const q = document.getElementById("q").value.toLowerCase();
  const showClosed = document.getElementById("sc").checked;
  for (const r of document.querySelectorAll("#t tbody tr")) {{
    const hideClosed = r.classList.contains("closed") && !showClosed;
    r.style.display = !hideClosed && r.innerText.toLowerCase().includes(q) ? "" : "none";
  }}
}}
function defaultSort() {{
  // Newest first by posted date (falling back to first-seen), score breaks ties.
  const tb = document.querySelector("#t tbody");
  [...tb.rows].sort((a, b) => {{
    const d = r => r.cells[5].innerText.trim() || r.cells[6].innerText.trim().slice(0, 10);
    const cmp = d(b).localeCompare(d(a));
    if (cmp) return cmp;
    return (parseFloat(b.cells[7].innerText) || -1) - (parseFloat(a.cells[7].innerText) || -1);
  }}).forEach(r => tb.appendChild(r));
  col = 5; dir = -1;
}}
// Documented default sort: fit band desc, then priority flag, then posted
// date desc (first-seen fallback), then pay presence. Within-band order is
// deterministic — no reliance on sub-band score precision.
function bandSort() {{
  const tb = document.querySelector("#t tbody");
  const s = r => parseFloat(r.cells[7].dataset.s ?? "-1");
  const d = r => r.cells[5].innerText.trim() || r.cells[6].innerText.trim().slice(0, 10);
  [...tb.rows].sort((a, b) =>
    (s(b) - s(a))
    || (b.classList.contains("priority") - a.classList.contains("priority"))
    || d(b).localeCompare(d(a))
    || ((b.cells[4].innerText.trim() ? 1 : 0) - (a.cells[4].innerText.trim() ? 1 : 0))
  ).forEach(r => tb.appendChild(r));
  col = 7; dir = -1;
}}
bandSort(); applyVis();
function ago() {{
  const el = document.getElementById("upd");
  const ts = new Date(el.dataset.ts);
  const mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
  const rel = mins < 1 ? "just now" : mins < 60 ? `${{mins}} min ago`
    : mins < 2880 ? `${{Math.round(mins / 60)}} h ago` : `${{Math.round(mins / 1440)}} days ago`;
  el.textContent = ts.toLocaleString(undefined, {{dateStyle: "medium", timeStyle: "short"}}) + ` (${{rel}})`;
  el.style.color = mins > 2160 ? "#d33" : "";  // red if stale >36h — a daily run was missed
}}
ago(); setInterval(ago, 30000);
</script>
</body>
</html>
"""


def _extra_locs(rec: dict) -> str:
    n = len(rec.get("locations") or []) - 1
    return f' <small>+{n} more</small>' if n > 0 else ""


def _row(rec: dict) -> str:
    classes = (["priority"] if rec.get("priority") else []) + (
        [] if rec.get("active", True) else ["closed"])
    cls = f' class="{" ".join(classes)}"' if classes else ""
    e = lambda s: html.escape(str(s or ""))
    score = rec.get("score")
    band = rec.get("band", "")
    fp = rec.get("scoring_fingerprint") or {}
    tooltip = e(rec.get("rationale"))
    if fp:
        tooltip += f' [{e(fp.get("model", ""))} · rubric {e(fp.get("rubric", ""))} · {e(fp.get("at", ""))}]'
    label = e(band or (str(score) if score is not None else ""))
    score_cell = (f'<td data-s="{score if score is not None else -1}" '
                  f'title="{tooltip}">{label}</td>')
    mode = {"onsite": "🏢 onsite", "hybrid": "🔀 hybrid", "remote": "🏠 remote"}.get(
        rec.get("work_mode", ""), "")
    first_seen = rec.get("first_seen", "")
    if not rec.get("active", True):
        first_seen += f' <small>(closed {rec.get("closed", "")})</small>'
    ref = quote(rec.get("title", "")[:80] + " @ " + rec.get("company", ""))
    fb_url = (f"https://github.com/{REPO}/issues/new?labels=feedback"
              f"&title={quote('feedback: ')}{ref}&body={quote(_feedback_body(rec))}")
    return (
        f'<tr{cls}><td><a href="{e(rec.get("url"))}" target="_blank">{e(rec.get("title"))}</a>'
        f'<br><small>{e(rec.get("source"))} · <a href="{fb_url}" target="_blank">feedback</a>'
        f'</small></td>'
        f'<td>{e(rec.get("company"))}</td><td>{e(rec.get("location"))}{_extra_locs(rec)}</td>'
        f'<td>{mode}</td><td>{e(rec.get("pay"))}</td>'
        f'<td>{e(rec.get("date_posted"))}</td><td>{first_seen}</td>{score_cell}</tr>'
    )


_STATUS_ICON = {"ok": "✅", "empty": "⚠️", "failed": "❌"}


def _health_row(s: dict) -> str:
    e = lambda v: html.escape(str(v or ""))
    return (
        f'<tr><td>{e(s["source"])}</td>'
        f'<td>{_STATUS_ICON.get(s["status"], "?")} {e(s["status"])}</td>'
        f'<td>{s["count"]}</td><td>{e(s["last_results"] or "never")}</td>'
        f'<td>{e(s["error"])}</td></tr>'
    )


def _select_rows(state: dict, max_rows: int) -> tuple[list[dict], int, int]:
    """Top-N active by score. Fresh rows (last 7 days) always show unless
    they alone exceed the cap — then even fresh rows rank by score. The
    closed toggle shows only genuine market closures (100 most recent):
    auto-archived misfits, feedback-hidden, and duplicate records stay in
    state for dedupe but are not listed."""
    active = [r for r in state.values() if r.get("active", True)]
    closed = [r for r in state.values() if not r.get("active", True)
              and not (r.get("lowscore") or r.get("hidden")
                       or r.get("excluded") or r.get("duplicate"))]
    fresh_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    def score_key(r):
        return -(r["score"] if r.get("score") is not None else -1)
    fresh = [r for r in active if r.get("first_seen", "") >= fresh_cutoff]
    backlog = sorted((r for r in active if r.get("first_seen", "") < fresh_cutoff),
                     key=score_key)
    if len(fresh) > max_rows:  # a flood week: even fresh rows rank by score
        fresh = sorted(fresh, key=score_key)[:max_rows]
    shown = fresh + backlog[:max(0, max_rows - len(fresh))]
    closed_shown = sorted(closed, key=lambda r: str(r.get("closed", "")), reverse=True)[:100]
    return shown + closed_shown, len(active), len(closed)


def generate(state: dict, health_summary: list[dict] | None = None,
             max_rows: int = 500) -> None:
    selected, active, closed = _select_rows(state, max_rows)
    records = sorted(selected, key=lambda r: r.get("first_seen", ""), reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shown_active = sum(1 for r in records if r.get("active", True))
    now = datetime.now(timezone.utc)
    OUT.write_text(_PAGE.format(
        active_count=(f"top {shown_active} of {active}"
                      if shown_active < active else str(active)),
        closed_count=closed,
        generated=now.strftime("%Y-%m-%d %H:%M"),
        generated_iso=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        rows="\n".join(_row(r) for r in records),
        health_rows="\n".join(_health_row(s) for s in health_summary or []),
    ))

"""Generate the static dashboard (docs/index.html) from state, for GitHub Pages."""
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from . import themes
from .util import best_link

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

# One-tap verdicts (owner, 2026-10-01). Each opens a pre-filled feedback
# issue; the next run moves that posting one band and the issue keeps
# steering future scoring (feedback.apply_verdicts).
VERDICTS = (
    ("higher", "👍 great fit", "Great fit, belongs higher"),
    ("lower", "🔧 too technical", "Too technical, belongs lower"),
    ("lower", "📉 experience", "Lack experience, belongs lower"),
    ("lower", "🏭 industry", "Wrong industry, belongs lower"),
)


# Verdict lines first; the scoring context sits below '---', which
# feedback.load strips before the issue reaches the scoring prompt.
VERDICT_BODY = ("Verdict: {direction}\nReason: {reason}\n\n"
                "Tap Create to send. Add notes here if you like.\n\n"
                "---\n<!-- job: {job_id} -->\nScored {band}.")


def _verdict_body(rec: dict, direction: str, reason: str) -> str:
    return VERDICT_BODY.format(direction=direction, reason=reason,
                               job_id=rec.get("_id", ""), band=_band(rec) or "?")


def _verdict_js() -> str:
    """Gives each verdict button its pre-filled feedback-issue URL the moment
    it is touched, hovered or focused, so a tap, a middle-click and a
    long-press "open in new tab" all reach the issue. Building the URLs here
    instead of in every row keeps the page near its old size."""
    return (
        "const VERDICTS = " + json.dumps([[d, r] for d, _, r in VERDICTS]) + ";\n"
        "const VERDICT_BODY = " + json.dumps(VERDICT_BODY) + ";\n"
        "function verdictHref(a) {\n"
        "  const tr = a.closest('tr'), [direction, reason] = VERDICTS[a.dataset.v];\n"
        "  const body = VERDICT_BODY.replace('{direction}', direction).replace('{reason}', reason)\n"
        "    .replace('{job_id}', tr.dataset.id).replace('{band}', tr.dataset.band);\n"
        "  a.href = 'https://github.com/" + REPO + "/issues/new?labels=feedback&title='\n"
        "    + encodeURIComponent('feedback: ' + tr.dataset.ref) + '&body=' + encodeURIComponent(body);\n"
        "}\n"
        "for (const type of ['pointerdown', 'mouseover', 'focusin', 'click'])\n"
        "  document.addEventListener(type, ev => {\n"
        "    const a = ev.target.closest && ev.target.closest('a.v');\n"
        "    if (a && a.getAttribute('href') === '#') verdictHref(a);\n"
        "  }, true);\n")


OUT = Path("docs/index.html")

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  {theme_css}
  * {{ box-sizing: border-box; }}
  body {{ font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0;
         background: var(--bg); color: var(--ink); }}
  main {{ max-width: 76rem; margin: 0 auto; padding: 0 1rem 3rem; }}
  .hero {{ position: relative; overflow: hidden; border-radius: 0 0 1.25rem 1.25rem;
          height: 15rem; color: #fff; margin-bottom: 1.25rem; }}
  .hero svg {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
  .hero::after {{ content: ""; position: absolute; inset: 0;
                 background: linear-gradient(90deg, #0008, #0000 65%); }}
  .hero .txt {{ position: relative; z-index: 1; padding: 2rem 1.5rem 1.6rem; max-width: 34rem; }}
  @media (max-width: 640px) {{ .hero {{ height: 12rem; }} .hero svg {{ opacity: .45; }} }}
  .hero h1 {{ margin: 0; font-size: clamp(1.6rem, 4vw, 2.4rem); font-weight: 800; letter-spacing: -.02em;
             text-shadow: 0 2px 12px #0006; }}
  .hero p {{ margin: .35rem 0 0; opacity: .85; text-shadow: 0 1px 8px #0006; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: .5rem; margin: 0 0 1rem; }}
  .chip {{ background: var(--card); border: 1px solid var(--border); border-radius: 999px;
          padding: .3rem .8rem; font-size: .85rem; color: var(--muted); }}
  .chip b {{ color: var(--ink); font-size: 1rem; margin-right: .2rem; }}
  .controls {{ display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; margin-bottom: .8rem; }}
  input[type=search] {{ padding: .5rem .8rem; width: 18rem; max-width: 100%; border-radius: .6rem;
                       border: 1px solid var(--border); background: var(--card); color: var(--ink); }}
  input[type=search]:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .meta {{ color: var(--muted); font-size: .85rem; }}
  .tablewrap {{ overflow-x: auto; background: var(--card); border: 1px solid var(--border);
               border-radius: 1rem; box-shadow: 0 1px 2px #0000000d; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .6rem .75rem; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ cursor: pointer; white-space: nowrap; user-select: none; background: var(--head);
       font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }}
  tbody tr:hover {{ background: var(--head); }}
  td:first-child > a:first-child {{ font-weight: 600; color: var(--ink); text-decoration: none; }}
  td:first-child > a:first-child:hover {{ color: var(--accent); text-decoration: underline; }}
  td small {{ color: var(--muted); }}
  .src {{ display: block; margin: .15rem 0 .35rem; }}
  .fb {{ display: flex; flex-wrap: wrap; gap: .3rem; }}
  .fb a {{ font-size: .75rem; padding: .1rem .5rem; border-radius: 999px; white-space: nowrap;
          border: 1px solid var(--border); color: var(--muted); text-decoration: none; background: var(--bg); }}
  .fb a:hover {{ border-color: var(--accent); color: var(--accent); }}
  tr.priority td:first-child::before {{ content: "⭐ "; }}
  tr.closed {{ opacity: .45; }}
  tr.closed td:first-child a {{ text-decoration: line-through; }}
  label {{ font-size: .85rem; user-select: none; color: var(--muted); }}
  .band {{ display: inline-block; padding: .15rem .55rem; border-radius: 999px; font-size: .8rem;
          font-weight: 700; white-space: nowrap; }}
  .band-top {{ background: var(--b-top); color: var(--b-top-ink); }}
  .band-strong {{ background: var(--b-strong); color: var(--b-strong-ink); }}
  .band-possible {{ background: var(--b-possible); color: var(--b-possible-ink); }}
  .band-weak {{ background: var(--b-weak); color: var(--b-weak-ink); }}
  .band-misfit {{ background: var(--b-misfit); color: var(--b-misfit-ink); }}
  h2 {{ font-size: 1.05rem; margin: 2rem 0 .6rem; }}
</style>
</head>
<body>
<header class="hero">{art}<div class="txt"><h1>{mark} {title}</h1><p>{tagline}</p></div></header>
<main>
<div class="chips"><span class="chip"><b>{active_count}</b>active{shown_note}</span><span class="chip"><b>{top_count}</b>top fits</span><span class="chip"><b>{new_count}</b>new this week</span><span class="chip"><b>{closed_count}</b>closed</span></div>
<div class="controls"><input id="q" type="search" placeholder="Filter by title, company, place…" oninput="applyVis()"><label><input id="sc" type="checkbox" onchange="applyVis()"> show closed</label><span class="meta">Updated <span id="upd" data-ts="{generated_iso}">{generated} UTC</span></span></div>
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
<h2>Source health</h2>
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
    // Title, company and location only: the row's buttons ("too technical",
    // "industry") would otherwise match every row.
    const text = (r.cells[0].querySelector("a").innerText + " " + r.cells[1].innerText
                  + " " + r.cells[2].innerText).toLowerCase();
    r.style.display = !hideClosed && text.includes(q) ? "" : "none";
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
// Documented default sort: fit band desc, then posted date desc (first-seen
// fallback), then priority flag, then pay presence. Newest first within a
// band: with the flag ahead of the date, weeks-old starred rows buried every
// new unstarred role. Within-band order is deterministic — no reliance on
// sub-band score precision.
function bandSort() {{
  const tb = document.querySelector("#t tbody");
  const s = r => parseFloat(r.cells[7].dataset.s ?? "-1");
  const d = r => r.cells[5].innerText.trim() || r.cells[6].innerText.trim().slice(0, 10);
  [...tb.rows].sort((a, b) =>
    (s(b) - s(a))
    || d(b).localeCompare(d(a))
    || (b.classList.contains("priority") - a.classList.contains("priority"))
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
{verdict_js}
</script>
</main>
</body>
</html>
"""


def _extra_locs(rec: dict) -> str:
    n = len(rec.get("locations") or []) - 1
    return f' <small>+{n} more</small>' if n > 0 else ""


BAND_SCORE = {"top": 90, "strong": 75, "possible": 55, "weak": 35, "misfit": 15}


def _band(rec: dict) -> str:
    """The band to show and sort by. Records scored before bands existed
    carry only a number (76, 82, 85...), and sorting on it put every one of
    them above every current strong (75) posting, burying new roles under
    months-old ones. They take the nearest band."""
    if rec.get("band") in BAND_SCORE:
        return rec["band"]
    score = rec.get("score")
    if score is None:
        return ""
    for name, floor in (("top", 82.5), ("strong", 65), ("possible", 45), ("weak", 25)):
        if score >= floor:
            return name
    return "misfit"


def _row(rec: dict, theme: dict | None = None) -> str:
    theme = theme or themes.get(None)
    classes = (["priority"] if rec.get("priority") else []) + (
        [] if rec.get("active", True) else ["closed"])
    cls = f' class="{" ".join(classes)}"' if classes else ""
    e = lambda s: html.escape(str(s or ""))
    fp = rec.get("scoring_fingerprint") or {}
    tooltip = e(rec.get("rationale"))
    if fp:
        tooltip += f' [{e(fp.get("model", ""))} · rubric {e(fp.get("rubric", ""))} · {e(fp.get("at", ""))}]'
    band = _band(rec)
    icon = theme["icons"].get(band, "")
    label = f'<span class="band band-{e(band)}">{icon} {e(band)}</span>' if band else ""
    score_cell = (f'<td data-s="{BAND_SCORE.get(band, -1)}" '
                  f'title="{tooltip}">{label}</td>')
    mode = {"onsite": "🏢 onsite", "hybrid": "🔀 hybrid", "remote": "🏠 remote"}.get(
        rec.get("work_mode", ""), "")
    first_seen = rec.get("first_seen", "")
    if not rec.get("active", True):
        first_seen += f' <small>(closed {rec.get("closed", "")})</small>'
    ref = quote(rec.get("title", "")[:80] + " @ " + rec.get("company", ""))
    # Built on tap from the row's data attributes (see VERDICT_JS): four
    # pre-filled URLs per row doubled the page to 2 MB.
    verdicts = "".join(
        f'<a class="v" data-v="{i}" href="#" target="_blank" title="{reason}">{label}</a>'
        for i, (_, label, reason) in enumerate(VERDICTS))
    fb_url = (f"https://github.com/{REPO}/issues/new?labels=feedback"
              f"&title={quote('feedback: ')}{ref}&body={quote(_feedback_body(rec))}")
    return (
        f'<tr{cls} data-id="{e(rec.get("_id"))}" data-band="{e(_band(rec) or "?")}"'
        f' data-ref="{e(rec.get("title", "")[:80] + " @ " + rec.get("company", ""))}">'
        f'<td><a href="{e(best_link(rec))}" target="_blank">{e(rec.get("title"))}</a>'
        f'<small class="src">{e(rec.get("source"))}</small>'
        f'<span class="fb">{verdicts}<a href="{fb_url}" target="_blank" title="Write your own note">✏️ note</a></span>'
        f'</td>'
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
    """Top-N active by band. Fresh rows (last 7 days) always show unless
    they alone exceed the cap — then even fresh rows rank by band. The
    closed toggle shows only genuine market closures (100 most recent):
    auto-archived misfits, feedback-hidden, and duplicate records stay in
    state for dedupe but are not listed."""
    active = [r for r in state.values() if r.get("active", True)]
    closed = [r for r in state.values() if not r.get("active", True)
              and not (r.get("lowscore") or r.get("hidden")
                       or r.get("excluded") or r.get("duplicate"))]
    fresh_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    def rank(r):
        # Band, then newest: a raw score would let pre-band numbers (82,
        # 85) outrank every current strong posting.
        return (BAND_SCORE.get(_band(r), -1), r.get("first_seen", ""))
    fresh = [r for r in active if r.get("first_seen", "") >= fresh_cutoff]
    backlog = sorted((r for r in active if r.get("first_seen", "") < fresh_cutoff),
                     key=rank, reverse=True)
    if len(fresh) > max_rows:  # a flood week: even fresh rows rank by band
        fresh = sorted(fresh, key=rank, reverse=True)[:max_rows]
    shown = fresh + backlog[:max(0, max_rows - len(fresh))]
    closed_shown = sorted(closed, key=lambda r: str(r.get("closed", "")), reverse=True)[:100]
    return shown + closed_shown, len(active), len(closed)


def generate(state: dict, health_summary: list[dict] | None = None,
             max_rows: int = 500, theme: str | None = None,
             title: str = "Job Watcher") -> None:
    theme = themes.get(theme)
    state = {jid: {**r, "_id": jid} for jid, r in state.items()}  # copies: the id rides on the row
    selected, active, closed = _select_rows(state, max_rows)
    records = sorted(selected, key=lambda r: r.get("first_seen", ""), reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shown_active = sum(1 for r in records if r.get("active", True))
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    live = [r for r in state.values() if r.get("active", True)]
    # The banner the digest shows at its top, served from Pages next to the page.
    (OUT.parent / "banner.svg").write_text(themes.banner_svg(theme, html.escape(title)))
    OUT.write_text(_PAGE.format(
        title=html.escape(title), theme_css=themes.css_vars(theme), art=theme["art"],
        verdict_js=_verdict_js(),
        mark=theme["mark"], tagline=html.escape(theme["tagline"]),
        top_count=sum(1 for r in live if _band(r) == "top"),
        new_count=sum(1 for r in live if r.get("first_seen", "") >= week_ago),
        active_count=str(active),
        shown_note=(f" · top {shown_active} shown" if shown_active < active else ""),
        closed_count=closed,
        generated=now.strftime("%Y-%m-%d %H:%M"),
        generated_iso=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        rows="\n".join(_row(r, theme) for r in records),
        health_rows="\n".join(_health_row(s) for s in health_summary or []),
    ))

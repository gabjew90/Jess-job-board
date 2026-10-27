"""Generate the static dashboard (docs/index.html) from state, for GitHub Pages."""
import html
import json
import re
from urllib.parse import unquote
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import themes
from .util import best_link

REPO = "gabjew90/Jess-job-board"


# One-tap verdicts (owner, 2026-10-01; good/bad/closed 2026-10-24). Each
# opens a pre-filled feedback issue. On the next run a fit verdict moves
# that posting one band and keeps steering future scoring; "closed" moves
# it to the closed list (feedback.apply_verdicts). Any why goes in the issue.
VERDICTS = (
    ("higher", "👍 good fit", "Good fit, belongs higher"),
    ("lower", "👎 bad fit", "Bad fit, belongs lower"),
    ("closed", "🚫 closed", "Posting is closed"),
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
        "    .replace('{job_id}', tr.dataset.ids || tr.dataset.id).replace('{band}', tr.dataset.band);\n"
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
  .why {{ display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
          margin: .15rem 0 .35rem; font-size: .8rem; line-height: 1.35; color: var(--muted); }}
  td.c-title {{ min-width: 24rem; }}
  .sim {{ white-space: nowrap; }}
  .c-posted {{ white-space: nowrap; }}
  .fb {{ display: flex; flex-wrap: wrap; gap: .3rem; }}
  .fb a {{ font-size: .75rem; padding: .1rem .5rem; border-radius: 999px; white-space: nowrap;
          border: 1px solid var(--border); color: var(--muted); text-decoration: none; background: var(--bg); }}
  .fb a:hover {{ border-color: var(--accent); color: var(--accent); }}
  tr.grp td {{ background: var(--head); font-weight: 800; font-size: .95rem; color: var(--ink);
              padding: .55rem .75rem; border-top: 2px solid var(--border); }}
  tr.grp small {{ font-weight: 400; color: var(--muted); margin-left: .4rem; }}
  .you {{ display: block; margin-top: .2rem; font-size: .72rem; color: var(--accent); white-space: nowrap; }}
  .legend {{ color: var(--muted); font-size: .85rem; margin: -.3rem 0 .9rem; max-width: 52rem; }}
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
  /* Phones: each posting becomes a card, so every detail fits the width
     with no sideways scrolling: title and rating on top, then company and
     place, then pay and work mode as pills (pay first), then the date on one
     small line, with the buttons last. The one-line reason for the rating
     sits under the company and place, cut at three lines. A stripe in the rating's colour runs
     down the card's edge; roles first seen today or yesterday carry a NEW
     badge. Cells are targeted by class (set in _row), not position. Column
     sorting needs the header, so phones keep the grouped rating order (the
     script restores it when the screen narrows). */
  @media (max-width: 640px) {{
    .hero {{ height: 12rem; }} .hero svg {{ opacity: .45; }}
    .boardwrap {{ background: none; border: 0; box-shadow: none; }}
    #t thead {{ display: none; }}
    #t, #t tbody {{ display: block; }}
    #t tr {{ display: flex; flex-wrap: wrap; align-items: center; gap: .35rem .45rem;
             margin: 0 0 .75rem; padding: .85rem .95rem .9rem 1.05rem;
             background: var(--card); border: 1px solid var(--border);
             border-left: 5px solid var(--b-possible); border-radius: .9rem;
             box-shadow: 0 2px 6px #0000000f; }}
    #t tr[data-band="top"] {{ border-left-color: var(--b-top); }}
    #t tr[data-band="strong"] {{ border-left-color: var(--b-strong); }}
    #t tr[data-band="weak"], #t tr[data-band="misfit"], #t tr[data-band="?"] {{
      border-left-color: var(--border); }}
    #t tbody tr:hover {{ background: var(--card); }}
    #t td {{ border: 0; padding: 0; min-width: 0; overflow-wrap: anywhere; }}
    #t td:empty {{ display: none; }}
    /* The title cell dissolves so its parts take their own places in the card. */
    #t td.c-title {{ display: contents; }}
    #t td.c-title > a:first-child {{ order: 1; flex: 1 1 0; min-width: 0; font-size: 1.05rem;
                                     line-height: 1.3; overflow-wrap: anywhere; }}
    #t tr.new td.c-title > a:first-child::after {{
      content: "NEW"; margin-left: .4rem; padding: .05rem .4rem; border-radius: .35rem;
      font-size: .65rem; font-weight: 800; letter-spacing: .06em; vertical-align: .15em;
      background: var(--b-top); color: var(--b-top-ink); }}
    #t td.c-fit {{ order: 2; flex: 0 0 auto; text-align: right; }}
    #t td.c-fit .band {{ font-size: .85rem; padding: .25rem .65rem; }}
    #t td.c-co {{ order: 3; flex-basis: 100%; font-weight: 600; }}
    #t td.c-co::before {{ content: "💼 "; }}
    #t td.c-loc {{ order: 4; flex-basis: 100%; color: var(--muted); }}
    #t td.c-loc::before {{ content: "📍 "; }}
    #t td.c-title > .why {{ order: 5; flex-basis: 100%; margin: 0; font-size: .82rem;
                            display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
                            overflow: hidden; }}
    #t td.c-pay {{ order: 6; padding: .2rem .6rem; border-radius: .7rem; font-weight: 700;
                   overflow-wrap: break-word; background: var(--money-bg); color: var(--money-ink); }}
    #t td.c-pay::before {{ content: "💵 "; }}
    #t td.c-mode {{ order: 7; padding: .2rem .6rem; border-radius: 999px; font-size: .85rem;
                    background: var(--head); }}
    #t td.c-posted {{ order: 8; margin: 0; font-size: .78rem; color: var(--muted); }}
    /* A zero-height break after the pills puts the date on its own line. */
    /* It forms a line of its own; the negative margin cancels its extra row gap. */
    #t tr:not(.grp)::after {{ content: ""; order: 7; flex-basis: 100%; height: 0;
                              margin-top: -.35rem; }}
    #t td.c-posted::before {{ content: "📅 "; }}
    #t td.c-title > .fb {{ order: 9; flex-basis: 100%; margin-top: .3rem; padding-top: .55rem;
                           border-top: 1px dashed var(--border); }}
    #t tr.grp {{ display: block; margin: 1.1rem 0 .55rem; padding: 0; background: none;
                 border: 0; box-shadow: none; }}
    #t tr.grp td {{ display: block; padding: 0 .2rem; background: none; border: 0;
                    font-size: 1.1rem; }}
  }}
</style>
</head>
<body>
<header class="hero">{art}<div class="txt"><h1>{mark} {title}</h1><p>{tagline}</p></div></header>
<main>
<div class="chips"><span class="chip">{active_chip}</span><span class="chip"><b>{top_count}</b>top fits</span><span class="chip"><b>{new_count}</b>new this week</span><span class="chip"><b>{closed_count}</b>closed</span></div>
<p class="legend">Roles are rated top, strong, possible, weak or misfit against the profile, newest first. Weak and misfit roles stay hidden unless you tick the box or search.<br>👍 good fit and 👎 bad fit move a role one rating on the next run and teach future ratings. 🚫 closed moves it to the closed list.</p>
<div class="controls"><input id="q" type="search" placeholder="Filter by title, company, place…" oninput="applyVis()"><label><input id="lo" type="checkbox" onchange="applyVis()"> show weak &amp; misfit</label><label><input id="sc" type="checkbox" onchange="applyVis()"> show closed</label><span class="meta">Updated <span id="upd" data-ts="{generated_iso}">{generated} UTC</span></span></div>
<div class="tablewrap boardwrap">
<table id="t">
<thead><tr>
  <th onclick="sortBy(0)">Title</th><th onclick="sortBy(1)">Company</th>
  <th onclick="sortBy(2)">Location</th><th onclick="sortBy(3)">Mode</th>
  <th onclick="sortBy(4)">Pay</th><th onclick="sortBy(5)">Posted</th>
  <th onclick="sortBy(6, true)">Fit</th>
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
let dir = -1, col = 5;
const GROUPS = {groups};
const LOW = ["weak", "misfit"];
function sortBy(c, numeric) {{
  // Fit toggles between the grouped order (best first) and a flat
  // lowest-first list, e.g. to review misfits.
  if (c === 6 && !(col === 6 && dir === -1)) {{ bandSort(); applyVis(); return; }}
  dir = (c === col) ? -dir : (numeric ? -1 : 1); col = c;
  const tb = document.querySelector("#t tbody");
  tb.querySelectorAll("tr.grp").forEach(g => g.remove());  // headings belong to the rating order
  [...tb.rows].sort((a, b) => {{
    const val = (r) => numeric ? parseFloat(r.cells[c].dataset.s ?? r.cells[c].innerText) || -1
                               : (r.cells[c].dataset.d ?? r.cells[c].innerText);
    return numeric ? dir * (val(a) - val(b)) : dir * val(a).localeCompare(val(b));
  }}).forEach(r => tb.appendChild(r));
  applyVis();
}}
function applyVis() {{
  const q = document.getElementById("q").value.toLowerCase();
  const showClosed = document.getElementById("sc").checked;
  // A search looks through every rating; only browsing hides weak and misfit.
  const showLow = document.getElementById("lo").checked || q !== "";
  for (const r of document.querySelectorAll("#t tbody tr:not(.grp)")) {{
    const hideClosed = (r.classList.contains("closed") && !showClosed)
      || (LOW.includes(r.dataset.band) && !showLow);
    // Title, company and location only: the row's buttons ("good fit",
    // "closed") would otherwise match every row.
    const text = (r.cells[0].querySelector("a").innerText + " " + r.cells[1].innerText
                  + " " + r.cells[2].innerText + " " + (r.dataset.places || "")).toLowerCase();
    r.style.display = !hideClosed && text.includes(q) ? "" : "none";
  }}
  // Each rating heading counts the rows showing under it, and hides at zero.
  let head = null, n = 0;
  const close = () => {{ if (head) {{ head.querySelector("small").textContent = n;
                                     head.style.display = n ? "" : "none"; }} }};
  for (const r of document.querySelectorAll("#t tbody tr")) {{
    if (r.classList.contains("grp")) {{ close(); head = r; n = 0; }}
    else if (r.style.display !== "none") n++;
  }}
  close();
}}
// Default order (owner, 2026-10-02): grouped by rating under a heading per
// rating, newest posted first within each (first-seen when the posting gave
// no date), then postings with pay. Within-rating order is deterministic: no
// reliance on sub-band score precision.
function bandSort() {{
  const tb = document.querySelector("#t tbody");
  tb.querySelectorAll("tr.grp").forEach(g => g.remove());
  const s = r => parseFloat(r.cells[6].dataset.s ?? "-1");
  const d = r => r.cells[5].dataset.d || "";
  const rows = [...tb.rows].sort((a, b) =>
    (s(b) - s(a))
    || d(b).localeCompare(d(a))
    || ((b.cells[4].innerText.trim() ? 1 : 0) - (a.cells[4].innerText.trim() ? 1 : 0)));
  let last = null;
  for (const r of rows) {{
    if (r.dataset.band !== last) {{
      last = r.dataset.band;
      const g = document.createElement("tr");
      g.className = "grp";
      g.innerHTML = `<td colspan="7">${{GROUPS[last] || "Not yet rated"}}<small></small></td>`;
      tb.appendChild(g);
    }}
    tb.appendChild(r);
  }}
  col = 6; dir = -1;
}}
bandSort(); applyVis();
// Phones have no column headers to sort by: narrowing to one (rotating a
// tablet) brings back the grouped rating order if a column sort removed it.
matchMedia("(max-width: 640px)").addEventListener("change", ev => {{
  if (ev.matches && !document.querySelector("#t tr.grp")) {{ bandSort(); applyVis(); }}
}});
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
// Each row's date reads as an age ("3 days ago"); the cell keeps the ISO
// date in data-d for sorting. A posting with no date of its own shows
// when the watcher first saw it.
function age(iso) {{
  const days = Math.round((Date.now() - new Date(iso + "T12:00:00Z")) / 86400000);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : days < 14 ? `${{days}} days ago`
    : days < 60 ? `${{Math.round(days / 7)}} weeks ago` : `${{Math.round(days / 30)}} months ago`;
}}
for (const td of document.querySelectorAll("#t td.c-posted[data-d]")) {{
  const when = age(td.dataset.d);
  td.firstChild.textContent = td.dataset.k === "seen" ? `seen ${{when}}` : when;
  td.title = (td.dataset.k === "seen" ? "First seen " : "Posted ") + td.dataset.d;
}}
{verdict_js}
</script>
</main>
</body>
</html>
"""


_N_LOCATIONS = re.compile(r"^\d+\s+locations?$", re.I)
_URL_PLACE = re.compile(r"\.myworkdayjobs\.com/.*?/job/([^/]+)/")


def _url_place(url: str) -> str:
    """The primary place Workday puts in a posting's link: /job/Columbus-OH/
    -> 'Columbus, OH'; /job/USA-TX-Austin/ -> 'Austin, TX'."""
    m = _URL_PLACE.search(url or "")
    if not m:
        return ""
    segment = re.sub(r"-\d{5}$", "", unquote(m.group(1)))   # trailing ZIP
    out = []
    for chunk in segment.split("---"):   # Workday writes ' - ' as '---'
        parts = [p for p in chunk.split("-") if p]
        if len(parts) >= 3 and parts[0] in ("USA", "US") and re.fullmatch(r"[A-Z]{2}", parts[1]):
            out.append(f"{' '.join(parts[2:])}, {parts[1]}")
        elif len(parts) >= 2 and re.fullmatch(r"[A-Z]{2}", parts[-1]):
            out.append(f"{' '.join(parts[:-1])}, {parts[-1]}")
        else:
            out.append(" ".join(parts))
    return ", ".join(o for o in out if o)


def _places(rec: dict) -> list[str]:
    """The posting's named places, deduped ('Charleston, WV, US' and
    'Charleston, WV' are one). A Workday 'N Locations' label carries no
    names, so the primary place comes from the link."""
    # ZIP codes (SuccessFactors writes 'Juno Beach, FL, US, 33408') add nothing.
    raw = [re.sub(r",?\s*\d{5}(-\d{4})?$", "", p.strip()) for p in
           (rec.get("locations") or [rec.get("location", "")]) if p and p.strip()]
    named = [p for p in raw if not _N_LOCATIONS.match(p)]
    labelled = max([int(p.split()[0]) for p in raw if _N_LOCATIONS.match(p)] or [0])
    if not named and labelled:
        primary = _url_place(rec.get("url", ""))
        if not primary:
            return []   # nothing to name: the cell shows the label as it is
        named = [primary]
    seen, out = set(), []
    for p in named:
        key = _place_key(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    # 'N Locations' says how many places there are; unnamed ones count in '+N'.
    return out + [""] * max(0, labelled - len(out))


def _place_key(place: str) -> str:
    return re.sub(r",\s*(US|USA|United States)$", "", (place or "").strip(), flags=re.I).lower()


_OWNER_NOTE = re.compile(r"^\s*Owner feedback \(#\d+\):[^.]*\.\s*")


def _reason(rec: dict) -> str:
    """The rating's one-line reason. The owner-verdict prefix the feedback
    step adds ('Owner feedback (#67): Great fit, belongs higher.') is left
    off: the '✓ your rating' mark already says it."""
    why = rec.get("rationale") or ""
    while _OWNER_NOTE.match(why):
        why = _OWNER_NOTE.sub("", why, count=1)
    return why[:177].rsplit(" ", 1)[0] + "…" if len(why) > 180 else why


def _place_parts(rec: dict) -> tuple[str, int, list[str]]:
    places = rec.get("_places") or _places(rec)
    named = [p for p in places if p]
    first = named[0] if named else re.sub(r",?\s*\d{5}(-\d{4})?$", "", rec.get("location") or "")
    return first, max(0, len(places) - 1), named


def place_summary(rec: dict) -> tuple[str, int]:
    """(first named place, how many more) for one posting or merged card."""
    return _place_parts(rec)[:2]


def _location_cell(rec: dict, e) -> str:
    """First named place, then '+N' for the rest (all named in the tooltip),
    then how many similar postings this card stands for."""
    first, more, named = _place_parts(rec)
    tip = f' title="{e("; ".join(named))}"' if len(named) > 1 else ""
    text = e(first) + (f' <small>+{more}</small>' if more > 0 else "")
    if rec.get("_similar"):
        text += f' <small class="sim">· {rec["_similar"]} postings</small>'
    return f'<td class="c-loc"{tip}>{text}</td>'


def _title_key(title: str) -> str:
    t = title or ""
    while True:   # parentheticals, nested included ("(PSO (Tulsa))")
        stripped = re.sub(r"\([^()]*\)", " ", t)
        if stripped == t:
            break
        t = stripped
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t.lower()).split())


def _merge_similar(records: list[dict]) -> list[dict]:
    """One card per role a company posts more than once: the same title,
    parentheticals aside (AEP's 'Project Manager | NEW GENERATION (PSO)' and
    '(Kentucky Power)'). The card is the best-rated, newest copy; it lists
    every place and says how many postings it stands for. Closed rows are
    never merged."""
    groups: dict[tuple, list[dict]] = {}
    order: list[list[dict]] = []
    for r in records:
        # The exact company name: company_key keeps only the first word
        # ('American Electric Power' and 'American Wire Group' share it).
        key = (" ".join(re.sub(r"[^a-z0-9]+", " ", (r.get("company") or "").lower()).split()),
               _title_key(r.get("title", "")))
        if not r.get("active", True) or not key[0] or not key[1]:
            order.append([r])
            continue
        if key not in groups:
            groups[key] = []
            order.append(groups[key])
        groups[key].append(r)
    out = []
    for g in order:
        if len(g) == 1:
            out.append(g[0])
            continue
        best = max(g, key=lambda r: (BAND_SCORE.get(_band(r), -1),
                                     r.get("date_posted") or r.get("first_seen", "")))
        # Named places only: a merged card's '+N' counts real places, not
        # the blank slots of 'N Locations' labels.
        places, seen = [], set()
        for r in [best] + [r for r in g if r is not best]:
            for p in _places(r):
                key = _place_key(p)
                if p and key not in seen:
                    seen.add(key)
                    places.append(p)
        out.append({**best, "_similar": len(g), "_places": places,
                    "_ids": [best["_id"]] + [r["_id"] for r in g if r is not best],
                    "_newest": max(r.get("first_seen", "") for r in g)})
    return out


# Rating headings, best first. Keys match triage.BAND_SCORE (a test holds
# them together).
GROUP_NAMES = {"top": "Top fits", "strong": "Strong fits", "possible": "Possible fits",
               "weak": "Weak fits", "misfit": "Misfits"}
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


def _row(rec: dict, theme: dict | None = None, fresh: str = "") -> str:
    """One posting's table row. `fresh` is the first-seen date from which a
    role counts as new (computed once per page by generate)."""
    theme = theme or themes.get(None)
    classes = ([] if rec.get("active", True) else ["closed"]) + (
        ["new"] if fresh and rec.get("active", True)
        and (rec.get("_newest") or rec.get("first_seen", "")) >= fresh else [])
    cls = f' class="{" ".join(classes)}"' if classes else ""
    e = lambda s: html.escape(str(s or ""))
    fp = rec.get("scoring_fingerprint") or {}
    tooltip = e(rec.get("rationale"))
    if fp:
        tooltip += f' [{e(fp.get("model", ""))} · rubric {e(fp.get("rubric", ""))} · {e(fp.get("at", ""))}]'
    band = _band(rec)
    icon = theme["icons"].get(band, "")
    label = f'<span class="band band-{e(band)}">{icon} {e(band)}</span>' if band else ""
    if fp.get("owner"):  # moved by one of the owner's verdicts
        label += '<small class="you">✓ your rating</small>'
    score_cell = (f'<td class="c-fit" data-s="{BAND_SCORE.get(band, -1)}" '
                  f'title="{tooltip}">{label}</td>')
    mode = {"onsite": "🏢 onsite", "hybrid": "🔀 hybrid", "remote": "🏠 remote"}.get(
        rec.get("work_mode", ""), "")
    # One date per row, shown as an age by the page script: when the
    # posting went up, or when the watcher first saw it if it gave no date.
    when, kind = (rec.get("date_posted"), "posted") if rec.get("date_posted") else (
        rec.get("first_seen", ""), "seen")
    closed = f' <small>(closed {e(rec.get("closed", ""))})</small>' if not rec.get("active", True) else ""
    date_cell = (f'<td class="c-posted" data-d="{e(when)}" data-k="{kind}">{e(when)}{closed}</td>'
                 if when else f'<td class="c-posted">{closed}</td>')
    why = _reason(rec)
    # Built on tap from the row's data attributes (see _verdict_js):
    # pre-filled issue URLs in every row doubled the page to 2 MB.
    verdicts = "".join(
        f'<a class="v" data-v="{i}" href="#" target="_blank" title="{reason}">{label}</a>'
        for i, (_, label, reason) in enumerate(VERDICTS))
    return (
        f'<tr{cls} data-id="{e(rec.get("_id"))}" data-band="{e(_band(rec) or "?")}"'
        + (f' data-ids="{e(" ".join(rec["_ids"]))}" data-places="{e("; ".join(p for p in rec["_places"] if p))}"'
           if rec.get("_ids") else "") +
        f' data-ref="{e(rec.get("title", "")[:80] + " @ " + rec.get("company", ""))}">'
        f'<td class="c-title"><a href="{e(best_link(rec))}" target="_blank">{e(rec.get("title"))}</a>'
        + (f'<small class="why">{e(why)}</small>' if why else "") +
        f'<span class="fb">{verdicts}</span>'
        f'</td>'
        f'<td class="c-co">{e(rec.get("company"))}</td>{_location_cell(rec, e)}'
        f'<td class="c-mode">{mode}</td><td class="c-pay">{e(rec.get("pay"))}</td>'
        f'{date_cell}{score_cell}</tr>'
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
    shown_active = sum(1 for r in records if r.get("active", True))   # postings, before merging
    records = _merge_similar(records)
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    fresh = (now - timedelta(days=1)).strftime("%Y-%m-%d")  # NEW: today or yesterday
    live = [r for r in state.values() if r.get("active", True)]
    # The banner the digest shows at its top, served from Pages next to the page.
    (OUT.parent / "banner.svg").write_text(themes.banner_svg(theme, html.escape(title)))
    OUT.write_text(_PAGE.format(
        title=html.escape(title), theme_css=themes.css_vars(theme), art=theme["art"],
        verdict_js=_verdict_js(),
        groups=json.dumps({b: f"{theme['icons'][b]} {name}" for b, name in GROUP_NAMES.items()}),
        mark=theme["mark"], tagline=html.escape(theme["tagline"]),
        top_count=sum(1 for r in live if _band(r) == "top"),
        new_count=sum(1 for r in live if r.get("first_seen", "") >= week_ago),
        active_chip=(f"<b>{shown_active:,}</b>shown of {active:,} active" if shown_active < active
                     else f"<b>{active:,}</b>active"),
        closed_count=closed,
        generated=now.strftime("%Y-%m-%d %H:%M"),
        generated_iso=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        rows="\n".join(_row(r, theme, fresh) for r in records),
        health_rows="\n".join(_health_row(s) for s in health_summary or []),
    ))

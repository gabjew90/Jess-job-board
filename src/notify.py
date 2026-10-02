"""Notification: post the day's new postings as a GitHub Issue.

Uses the workflow's own GITHUB_TOKEN — no extra secrets. Locally (no token)
the digest is just printed.
"""
import logging
import os

import requests

from .models import Job
from . import themes
from .util import best_link
from .dashboard import GROUP_NAMES, _band

POSSIBLE_CAP = 25  # one-line rows per lower rating before "…and N more"


def dashboard_url() -> str:
    """The GitHub Pages URL for this repo's dashboard, derived from the
    repository so a fork points at its own board rather than the original."""
    from .dashboard import REPO  # noqa: PLC0415 - read at call time so tests can patch it
    repo = os.environ.get("GITHUB_REPOSITORY") or REPO
    owner, _, name = repo.partition("/")
    return f"https://{owner}.github.io/{name}/"

log = logging.getLogger(__name__)


def _esc(text: str, limit: int = 0) -> str:
    text = (text or "").replace("|", "\\|").replace("\n", " ").strip()
    return text[:limit] + "…" if limit and len(text) > limit else text


def _rev_date(d: str) -> str:
    return "".join(chr(255 - ord(c)) for c in (d or "0000-00-00"))


def _newest(r: dict):
    """Order within a rating: newest posted first (first-seen when the
    posting gave no date), then postings with pay, matching the dashboard;
    no sub-band precision implied."""
    return (_rev_date(r.get("date_posted") or r.get("first_seen", "")),
            not r.get("pay"))


def _above_floor(records: list[dict], digest_floor: int) -> list[dict]:
    """The records the digest itemizes: unscored ones and those at or above
    the floor. Clear misfits are only counted."""
    return [r for r in records if r.get("score") is None or r["score"] >= digest_floor]


def build_digest(records: list[dict],
                 health_summary: list[dict] | None = None,
                 closed_recs: list[dict] | None = None,
                 digest_floor: int = 40,
                 unresolved: list[dict] | None = None,
                 audit_recs: list[dict] | None = None,
                 discovered: list[dict] | None = None,
                 reject_audit: list[dict] | None = None,
                 screen_stats: dict | None = None,
                 theme: str | None = None) -> str:
    """Render the digest from STATE RECORDS covering a rolling window, so a
    posting appears in every digest for 24h. Runs fire several times a day
    (GitHub's cron is erratic); a run-scoped digest meant anything found
    between two digests could be missed entirely."""
    th = themes.get(theme)
    lines = [f"[![{th['tagline']}]({dashboard_url()}banner.svg)]({dashboard_url()})",
             ""]
    # Digest floor: don't itemize clear misfits, just count them.
    visible = _above_floor(records, digest_floor)
    omitted = len(records) - len(visible)
    groups: dict[str, list[dict]] = {}
    for r in visible:
        groups.setdefault(_band(r) or "", []).append(r)
    counts = " · ".join(f"{th['icons'][b]} **{len(groups[b])}** {b}"
                        for b in GROUP_NAMES if groups.get(b))
    if groups.get(""):
        counts += f"{' · ' if counts else ''}⏳ **{len(groups[''])}** not yet rated"
    lines.append(f"{counts or 'Nothing above the floor'} in the last 24h. "
                 f"**[Open the full board]({dashboard_url()})** for every posting "
                 "and one-tap feedback.\n")
    # Top and strong roles get a full row with the rationale, lower ones a
    # line each. Rated weak and misfit roles sit below the digest floor and
    # only count toward `omitted`; their sections catch legacy records that
    # carry just a number above the floor (40-44 reads as weak).
    for band in ("top", "strong"):
        if not groups.get(band):
            continue
        lines.append(f"\n## {th['icons'][band]} {GROUP_NAMES[band]}\n")
        lines.append("| Role | Company | Location | Mode | Pay | Posted |")
        lines.append("|---|---|---|---|---|---|")
        for r in sorted(groups[band], key=_newest):
            rationale = (f"<br><sub>{_esc(r['rationale'], 160)}</sub>"
                         if r.get("rationale") else "")
            locs = len(r.get("locations") or [])
            extra = f" +{locs - 1}" if locs > 1 else ""
            lines.append(
                f"| [{_esc(r.get('title'), 70)}]({best_link(r)}){rationale} "
                f"| {_esc(r.get('company'))} | {_esc(r.get('location'), 34)}{extra} "
                f"| {r.get('work_mode', '')} | {_esc(r.get('pay'), 45)} | {r.get('date_posted', '')} |")
    for band, heading in (("possible", None), ("weak", None), ("misfit", None), ("", "Not yet rated")):
        rows = sorted(groups.get(band, []), key=_newest)
        if not rows:
            continue
        name = heading or GROUP_NAMES[band]
        icon = th["icons"].get(band, "⏳")
        lines.append(f"\n## {icon} {name}\n")
        for r in rows[:POSSIBLE_CAP]:
            pay = f" · {_esc(r.get('pay'), 45)}" if r.get("pay") else ""
            lines.append(f"- [{_esc(r.get('title'), 70)}]({best_link(r)}) · "
                         f"{_esc(r.get('company'))} · {_esc(r.get('location'), 34)}{pay}")
        if len(rows) > POSSIBLE_CAP:
            lines.append(f"- …and {len(rows) - POSSIBLE_CAP} more on the board")
    if omitted:
        lines.append(f"\n_{omitted} low-fit posting{'s' if omitted != 1 else ''} "
                     f"(score < {digest_floor}) omitted; clear misfits are "
                     f"auto-archived._")
    if records and all(r.get("score") is None for r in records):
        lines.append("\n_Unscored run (triage unavailable)._")
    if closed_recs:
        lines.append("\n## 🚫 Closed since last run\n")
        by_score = sorted(closed_recs, key=lambda r: -(r.get("score") or -1))
        for r in by_score[:30]:
            score = f"{r['score']} · " if r.get("score") is not None else ""
            lines.append(f"- ~~{_esc(r.get('title', ''), 70)}~~ — {_esc(r.get('company', ''))} ({score}first seen {r.get('first_seen', '?')})")
        if len(closed_recs) > 30:
            lines.append(f"- …and {len(closed_recs) - 30} more")
    if audit_recs:
        lines.append("\n## 🧪 Weekly archive audit\n")
        lines.append("Random sample of auto-archived postings — check any the "
                     "filter got WRONG and file feedback on them:")
        for r in audit_recs:
            lines.append(f"- [ ] {r.get('band', r.get('score', '?'))}: "
                         f"[{_esc(r.get('title', ''), 60)}]({best_link(r)}) — "
                         f"{_esc(r.get('company', ''))}"
                         f"<br><sub>{_esc(r.get('rationale', ''), 140)}</sub>")
    if reject_audit:
        lines.append("\n## 🧪 Weekly filter audit\n")
        how = ("the title screen" if (screen_stats or {}).get("available")
               else "the keyword filter")
        stats = ""
        if (screen_stats or {}).get("screened"):
            stats = (f" This run the screen judged {screen_stats['screened']} "
                     f"titles, rescued {screen_stats['rescued']} past the "
                     f"keyword filter and dropped {screen_stats['dropped']} it "
                     f"had passed.")
        lines.append(f"Random sample of postings {how} turned away BEFORE "
                     f"scoring this run — these never reach state, so this is "
                     f"the only view of what the filter loses. Check any that "
                     f"should have been scored and file feedback:{stats}")
        for r in reject_audit:
            lines.append(f"- [ ] [{_esc(r.get('title', ''), 60)}]({best_link(r)}) — "
                         f"{_esc(r.get('company', ''))} · {_esc(r.get('location', ''), 30)}"
                         f" <sub>{_esc(r.get('source', ''))}</sub>")
    if discovered:
        lines.append("\n## 🔗 Direct boards wired up\n")
        lines.append("These companies kept surfacing strong roles through "
                     "aggregators, so their own boards are now tracked "
                     "(canonical links, full descriptions, exact expiry):")
        lines += [f"- **{d['company']}** — {d['provider']} `{d['board']}`"
                  for d in discovered]
    if unresolved:
        lines.append("\n## 🔭 No direct board found\n")
        lines.append("Strong roles from these companies reach us only through "
                     "Indeed. Their postings linked no careers board we can "
                     "read and no board guess matched. Retried automatically "
                     "in 30 days, or sooner if a new posting links a board:")
        for u in sorted(unresolved, key=lambda u: -(u.get("score") or 0)):
            lines.append(f"- **{_esc(u['company'])}** (top {u['score']}: "
                         f"{_esc(u.get('title', ''), 55)})")
    unhealthy = [s for s in health_summary or [] if s["status"] != "ok"]
    if unhealthy:
        lines.append("\n## ⚠️ Source issues\n")
        for s in unhealthy:
            detail = s["error"] or "returned 0 results"
            lines.append(f"- `{s['source']}`: {s['status']} ({detail[:120]}) — "
                         f"last results {s['last_results'] or 'never'}")
    lines.append(f"\n---\n_Full board with every posting and its history: {dashboard_url()}_")
    return "\n".join(lines)




def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip(" ,-–") + "…"


def digest_title(records: list[dict], closed_recs: list[dict] | None = None,
                 digest_floor: int = 40, theme: str | None = None) -> str:
    """The issue title, which is also the notification email's subject, so
    it leads with the best role (owner, 2026-10-02): "⚡ Top fit: Senior
    Product Manager at Google (+2 top, 5 strong)". The role named is the
    first row of the digest's best section. The tally comes last: a phone
    inbox may cut it, and the role matters more. GitHub adds the repo name
    and issue number around the title."""
    th = themes.get(theme)
    visible = _above_floor(records, digest_floor)
    groups: dict[str, list[dict]] = {}
    for r in visible:
        groups.setdefault(_band(r) or "", []).append(r)
    unrated = len(groups.get("", []))
    # Weak roles (legacy scores just above the floor) never headline.
    band = next((b for b in ("top", "strong", "possible")
                 if any((r.get("title") or "").strip() for r in groups.get(b, []))), None)
    if band:
        best = next(r for r in sorted(groups[band], key=_newest)
                    if (r.get("title") or "").strip())
        role = _short(best["title"], 45)
        if (best.get("company") or "").strip():
            role += f" at {_short(best['company'], 25)}"
        label = {"top": "Top fit", "strong": "Strong fit"}.get(band, "Possible fit")
        others = [f"{len(groups.get(b, [])) - (b == band)} {b}" for b in ("top", "strong")
                  if len(groups.get(b, [])) - (b == band) > 0]
        if unrated:
            others.append(f"{unrated} unrated")
        title = f"{th['icons'][band]} {label}: {role}" + (f" (+{', '.join(others)})" if others else "")
    elif unrated:
        title = f"⏳ {unrated} new posting{'s' if unrated != 1 else ''}, not yet rated"
    else:
        title = "Job watch: no new fits"
    if closed_recs:
        title += f" · {len(closed_recs)} closed"
    return title


def post_issue(records: list[dict],
               health_summary: list[dict] | None = None,
               closed_recs: list[dict] | None = None,
               digest_floor: int = 40,
               unresolved: list[dict] | None = None,
               audit_recs: list[dict] | None = None,
               discovered: list[dict] | None = None,
               reject_audit: list[dict] | None = None,
               screen_stats: dict | None = None,
               theme: str | None = None) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    title = digest_title(records, closed_recs, digest_floor, theme)
    body = build_digest(records, health_summary, closed_recs,
                        digest_floor, unresolved, audit_recs, discovered,
                        reject_audit, screen_stats, theme)

    if not token or not repo:
        log.info("No GITHUB_TOKEN/GITHUB_REPOSITORY; printing digest instead.\n\n%s\n%s", title, body)
        return

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"title": title, "body": body, "labels": ["job-digest"]},
        timeout=30,
    )
    if resp.status_code == 201:
        log.info("Posted digest issue: %s", resp.json().get("html_url"))
    else:
        log.warning("Failed to post issue (%s): %s", resp.status_code, resp.text[:500])

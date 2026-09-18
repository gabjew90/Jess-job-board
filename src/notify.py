"""Notification: post the day's new postings as a GitHub Issue.

Uses the workflow's own GITHUB_TOKEN — no extra secrets. Locally (no token)
the digest is just printed.
"""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from .models import Job

log = logging.getLogger(__name__)


AGGREGATOR_SOURCES = {"indeed", "glassdoor", "zip_recruiter", "google"}


def coverage_suggestions(seen: dict, config: dict) -> list[str]:
    """Companies whose postings score >=70 but reach us only via aggregators
    — candidates for a direct board. Suggested once, the day the company
    first crosses the bar."""
    from datetime import datetime, timezone
    from .util import company_key
    direct = {company_key(e.get("company", ""))
              for key in ("ats_boards", "workday_boards", "successfactors_boards",
                          "career_sites")
              for e in config.get(key, [])}
    # Watched employers are deliberately boardless (no reachable ATS) —
    # per the coverage doctrine they are covered, not candidates.
    direct |= {company_key(c) for c in config.get("indeed_company_watch", [])}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_company: dict[str, list[dict]] = {}
    for r in seen.values():
        if r.get("active", True) and r.get("company"):
            by_company.setdefault(r["company"], []).append(r)
    out = []
    for company, recs in by_company.items():
        if company_key(company) in direct:
            continue
        if not all(r.get("source") in AGGREGATOR_SOURCES for r in recs):
            continue
        best = max(recs, key=lambda r: r.get("score") or 0)
        if (best.get("score") or 0) >= 70 and best.get("first_seen") == today:
            out.append(f"**{company}** (top {best['score']}: "
                       f"{_esc(best.get('title', ''), 55)})")
    return out[:6]


def _esc(text: str, limit: int = 0) -> str:
    text = (text or "").replace("|", "\\|").replace("\n", " ").strip()
    return text[:limit] + "…" if limit and len(text) > limit else text


def build_digest(records: list[dict],
                 health_summary: list[dict] | None = None,
                 closed_recs: list[dict] | None = None,
                 digest_floor: int = 40,
                 suggestions: list[str] | None = None,
                 audit_recs: list[dict] | None = None,
                 discovered: list[dict] | None = None,
                 reject_audit: list[dict] | None = None,
                 screen_stats: dict | None = None) -> str:
    """Render the digest from STATE RECORDS covering a rolling window, so a
    posting appears in every digest for 24h. Runs fire several times a day
    (GitHub's cron is erratic); a run-scoped digest meant anything found
    between two digests could be missed entirely."""
    def sort_key(r: dict):
        # Band desc, priority flag, posted date desc — deterministic
        # within-band ordering, no sub-band precision implied.
        return (-(r.get("score") or -1), not r.get("priority"),
                _rev_date(r.get("date_posted", "")))

    def _rev_date(d: str) -> str:
        return "".join(chr(255 - ord(c)) for c in (d or "0000-00-00"))

    lines = []
    # Digest floor: don't itemize clear misfits, just count them.
    visible = [r for r in records
               if r.get("score") is None or r["score"] >= digest_floor]
    omitted = len(records) - len(visible)
    if visible:
        lines.append("| Fit | Role | Company | Location | Mode | Pay | Posted |")
        lines.append("|--:|---|---|---|---|---|---|")
        for r in sorted(visible, key=sort_key):
            band = r.get("band") or r.get("score")
            score = f"**{band}**" if band is not None else "–"
            star = " ⭐" if r.get("priority") else ""
            rationale = (f"<br><sub>{_esc(r['rationale'], 160)}</sub>"
                         if r.get("rationale") else "")
            locs = len(r.get("locations") or [])
            extra = f" +{locs - 1}" if locs > 1 else ""
            lines.append(
                f"| {score}{star} | [{_esc(r.get('title'), 70)}]({r.get('url')}){rationale} "
                f"| {_esc(r.get('company'))} | {_esc(r.get('location'), 34)}{extra} "
                f"| {r.get('work_mode', '')} | {_esc(r.get('pay'), 45)} | {r.get('date_posted', '')} |")
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
                         f"[{_esc(r.get('title', ''), 60)}]({r.get('url', '')}) — "
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
            lines.append(f"- [ ] [{_esc(r.get('title', ''), 60)}]({r.get('url', '')}) — "
                         f"{_esc(r.get('company', ''))} · {_esc(r.get('location', ''), 30)}"
                         f" <sub>{_esc(r.get('source', ''))}</sub>")
    if discovered:
        lines.append("\n## 🔗 Direct boards wired up\n")
        lines.append("These companies kept surfacing strong roles through "
                     "aggregators, so their own boards are now tracked "
                     "(canonical links, full descriptions, exact expiry):")
        lines += [f"- **{d['company']}** — {d['provider']} `{d['board']}`"
                  for d in discovered]
    if suggestions:
        lines.append("\n## 🔭 Coverage suggestions\n")
        lines.append("High scorers from companies we only see via aggregators "
                     "— name one in chat to get its direct board probed:")
        lines += [f"- {s}" for s in suggestions]
    unhealthy = [s for s in health_summary or [] if s["status"] != "ok"]
    if unhealthy:
        lines.append("\n## ⚠️ Source issues\n")
        for s in unhealthy:
            detail = s["error"] or "returned 0 results"
            lines.append(f"- `{s['source']}`: {s['status']} ({detail[:120]}) — "
                         f"last results {s['last_results'] or 'never'}")
    lines.append("\n---\n_Dashboard: see the GitHub Pages site for full history._")
    return "\n".join(lines)




def post_issue(records: list[dict],
               health_summary: list[dict] | None = None,
               closed_recs: list[dict] | None = None,
               digest_floor: int = 40,
               suggestions: list[str] | None = None,
               audit_recs: list[dict] | None = None,
               discovered: list[dict] | None = None,
               reject_audit: list[dict] | None = None,
               screen_stats: dict | None = None) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"Job watch {date}: {len(records)} posting{'s' if len(records) != 1 else ''} in 24h"
    banded = [r for r in records if r.get("band")]
    if banded:
        best = max(banded, key=lambda r: r.get("score") or 0)
        title += f" (top: {best['band']})"
    if closed_recs:
        title += f", {len(closed_recs)} closed"
    body = build_digest(records, health_summary, closed_recs,
                        digest_floor, suggestions, audit_recs, discovered,
                        reject_audit, screen_stats)

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

"""User feedback on specific jobs/patterns, from two places:

1. feedback.md in the repo — the curated preference file.
2. Open GitHub issues labeled `feedback` — created from the dashboard's
   per-row verdict buttons (good fit, bad fit, closed). Requires GITHUB_TOKEN, so
   issue feedback applies on workflow runs; local runs use feedback.md only.

Everything is injected verbatim into the triage scoring prompt so scores
adapt to the stated "why". Additionally, hide directives are applied
deterministically (no LLM involved):
- in feedback.md: a line like      hide: transmission planning @ ICF
- in a feedback issue: a body line  Action: hide, typed by hand
  (the job reference comes from the issue title "feedback: <title> @ <co>")

A hide target matches any job whose "<title> @ <company>" contains every
comma-free token group (case-insensitive substring on the whole string).
Hidden jobs are dropped before triage/digest and marked inactive in state.
"""
import logging
import os
import re
from pathlib import Path

import requests

from .models import Job
from .state import _today, suppressed

log = logging.getLogger(__name__)

FILE = Path("feedback.md")

# The repo is public: anyone can open an issue. Only these, plus the
# logins in config "feedback_authors" (Jess files from her own account),
# may move, close or hide postings or reach the scoring prompt.
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
MAX_PAGES = 30   # 3,000 open issues; digests stay open, about 2 a day


def _issue_entries() -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return []
    try:
        # Every open issue, not just the newest 100. The title prefix is the
        # sure mark: the live feedback issues carry no label (some clients
        # drop `labels=` from the new-issue URL), so no server-side filter.
        issues = []
        for page in range(1, MAX_PAGES + 1):
            resp = requests.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={"state": "open", "per_page": 100, "page": page},
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json"},
                timeout=30,
            )
            resp.raise_for_status()
            issues += resp.json()
            if len(resp.json()) < 100:
                break
        else:
            log.warning("feedback: %d+ open issues; older feedback issues are not read. "
                        "Close old digest issues.", MAX_PAGES * 100)
        return [{"number": i.get("number"), "title": i.get("title", ""),
                 "body": i.get("body") or "", "created": (i.get("created_at") or "")[:10],
                 "author": (i.get("user") or {}).get("login", ""),
                 "association": i.get("author_association", "")}
                for i in issues
                if not i.get("pull_request")
                and ("feedback" in {lb.get("name") for lb in i.get("labels") or []}
                     or i.get("title", "").lower().startswith("feedback:"))]
    except Exception as e:  # noqa: BLE001
        log.warning("feedback issue fetch failed: %s", e)
        return []


def load(authors: list[str] | tuple = ()) -> dict:
    """Return {"text": prompt block, "hide": [substring, ...],
    "verdicts": [{"issue", "job_id", "target", "direction", "reason"}]}.
    Issues count only from the owner, collaborators and `authors`."""
    parts: list[str] = []
    hide: list[str] = []
    verdicts: list[dict] = []

    if FILE.exists():
        # HTML comments hold inert examples — never parse or forward them.
        md = re.sub(r"<!--.*?-->", "", FILE.read_text(), flags=re.S).strip()
        # hide: lines are applied deterministically below and kept OUT of
        # the scoring prompt — shown the directive, the scorer skipped the
        # hidden posting instead of banding it (eval: no result returned).
        prompt_lines = []
        for line in md.splitlines():
            m = re.match(r"\s*[-*]?\s*hide:\s*(.+)", line, re.I)
            if m:
                hide.append(m.group(1).strip())
            else:
                prompt_lines.append(line)
        parts.append("\n".join(prompt_lines).strip())

    allowed = {a.lower() for a in authors}
    for issue in _issue_entries():
        if ("association" in issue and issue["association"] not in TRUSTED
                and issue.get("author", "").lower() not in allowed):
            log.info("Feedback: ignoring issue #%s from %s", issue.get("number"),
                     issue.get("author") or "unknown")
            continue
        body = issue["body"]
        # Strip pre-filled template text so only the owner's own notes reach
        # scoring. The how-this-was-scored split is for issues opened from
        # the retired note button (before 2026-10-24) that are still open.
        if "feed directly into future scoring:" in body:
            body = body.split("feed directly into future scoring:", 1)[1]
        body = re.sub(r"^---\s*$.*", "", body, flags=re.S | re.M)
        body = re.sub(r"^\s*Action:\s*hide\b.*$", "", body, flags=re.I | re.M)
        # Only the prompt itself: a note typed on the same line is kept.
        body = re.sub(r"^Tap Create to send\.(?: Add notes here if you like\.)?", "", body,
                      flags=re.M).strip()
        v = re.search(r"^\s*Verdict:\s*(higher|lower|closed)\b", issue["body"], re.I | re.M)
        # A "closed" report says nothing about fit, so it stays out of scoring.
        if not (v and v.group(1).lower() == "closed"):
            parts.append(f"[issue] {issue['title']}\n{body}".strip())
        if v:
            r = re.search(r"^\s*Reason:\s*(.+)$", issue["body"], re.I | re.M)
            # One id, or several when the board merged similar postings
            # into one card: the verdict applies to each of them.
            j = re.search(r"<!--\s*job:\s*([0-9a-f]+(?:\s+[0-9a-f]+)*)\s*-->", issue["body"])
            verdicts.append({
                "issue": issue.get("number"), "job_id": j.group(1).split()[0] if j else None,
                "job_ids": j.group(1).split() if j else [],
                "target": re.sub(r"^feedback:\s*", "", issue["title"], flags=re.I).strip(),
                "direction": v.group(1).lower(), "reason": r.group(1).strip() if r else "",
                "created": issue.get("created", "")})
        if re.search(r"^\s*Action:\s*hide\b", issue["body"], re.I | re.M):
            target = re.sub(r"^feedback:\s*", "", issue["title"], flags=re.I).strip()
            if target:
                hide.append(target)

    return {"text": "\n\n".join(p for p in parts if p), "hide": hide,
            "verdicts": verdicts}


def apply_verdicts(seen: dict, verdicts: list[dict], archive_below: int = 25) -> int:
    """Move each verdict's posting one band, once per issue, or close it
    for a "closed" verdict. The issue stays open as scoring guidance; the
    record remembers which issues it has absorbed, so later runs do not
    move it again, and the owner stamp keeps re-scoring from overwriting
    the owner's call."""
    from .triage import BAND_ORDER, BAND_SCORE
    n = 0
    today = _today()
    for v in verdicts:
        # By id; otherwise only the same title at the same company. A
        # substring match would move every "Engineer @ PG&E" each run.
        key = v["target"].lower().strip()
        ids = [i for i in (v.get("job_ids") or [v.get("job_id")]) if i in seen]
        recs = ([seen[i] for i in ids] if ids else
                [r for r in seen.values() if key and key in {
                    f"{t} @ {r.get('company', '')}".lower().strip()
                    for t in (r.get("title", ""), r.get("title", "")[:80])}])  # dashboard cuts titles at 80
        for rec in recs:
            done = rec.setdefault("verdicts_applied", [])
            if v["issue"] in done:
                continue
            if v["direction"] == "closed":
                # Only the posting the card links to: a merged card's other
                # cities were not checked and may still be open.
                listed = v.get("job_ids") or [v.get("job_id")]
                if (v.get("job_ids") or v.get("job_id")) and rec is not seen.get(listed[0]):
                    continue
                # Only postings seen before the report: the issue stays open,
                # and a later repost of the same role is a new opening.
                if v.get("created") and rec.get("first_seen", "") > v["created"]:
                    continue
                rec.update(active=False, owner_closed=True, lowscore=False)
                rec.setdefault("closed", today)
                done.append(v["issue"])
                n += 1
                continue
            if rec.get("band") not in BAND_ORDER:
                continue
            i = BAND_ORDER.index(rec["band"]) + (1 if v["direction"] == "higher" else -1)
            band = BAND_ORDER[max(0, min(i, len(BAND_ORDER) - 1))]
            rec.update(band=band, score=BAND_SCORE[band])
            # Kept apart from the model's rationale, which the board shows
            # as the rating's reason (older records carry it as a prefix).
            rec.setdefault("owner_notes", []).append(f"#{v['issue']}: {v['reason']}")
            fp = rec.setdefault("scoring_fingerprint", {})
            fp["owner"] = today
            if rec["score"] < archive_below and rec.get("active", True):
                rec.update(active=False, lowscore=True, closed=today)
            elif rec["score"] >= archive_below and rec.get("lowscore") and not suppressed(rec):
                rec.update(active=True, lowscore=False)  # raised out of the archive
                rec.pop("closed", None)
            done.append(v["issue"])
            n += 1
    if n:
        log.info("Feedback: applied %d one-tap verdicts", n)
    return n


def _match_one(target: str, title: str, company: str) -> bool:
    target = target.lower().strip()
    title, company = title.lower(), company.lower()
    if "@" in target:
        # "some title words @ company" — both halves match independently,
        # so shorthand works ("transmission planning @ icf").
        t, c = target.rsplit("@", 1)
        return t.strip() in title and c.strip() in company
    return target in f"{title} @ {company}"


def matches(job: Job, hide: list[str]) -> bool:
    return any(_match_one(h, job.title, job.company) for h in hide)


def sweep_state(seen: dict, hide: list[str]) -> int:
    """Mark already-tracked matching records hidden/inactive."""
    n = 0
    for rec in seen.values():
        if rec.get("hidden") or not hide:
            continue
        if any(_match_one(h, rec.get("title", ""), rec.get("company", ""))
               for h in hide):
            rec["hidden"] = True
            rec["active"] = False
            rec.setdefault("closed", _today())
            n += 1
    if n:
        log.info("Feedback: hid %d tracked postings", n)
    return n

"""User feedback on specific jobs/patterns, from two places:

1. feedback.md in the repo — the curated preference file.
2. Open GitHub issues labeled `feedback` — created from the dashboard's
   per-row "feedback" link (mobile-friendly). Requires GITHUB_TOKEN, so
   issue feedback applies on workflow runs; local runs use feedback.md only.

Everything is injected verbatim into the triage scoring prompt so scores
adapt to the stated "why". Additionally, hide directives are applied
deterministically (no LLM involved):
- in feedback.md: a line like      hide: transmission planning @ ICF
- in a feedback issue: a body line  Action: hide
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

log = logging.getLogger(__name__)

FILE = Path("feedback.md")


def _issue_entries() -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return []
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/issues",
            params={"state": "open", "per_page": 100},
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=30,
        )
        resp.raise_for_status()
        # By label OR by the dashboard's "feedback:" title prefix: some
        # clients drop the `labels=` parameter from the new-issue URL.
        return [{"title": i.get("title", ""), "body": i.get("body") or ""}
                for i in resp.json()
                if not i.get("pull_request")
                and ("feedback" in {lb.get("name") for lb in i.get("labels") or []}
                     or i.get("title", "").lower().startswith("feedback:"))]
    except Exception as e:  # noqa: BLE001
        log.warning("feedback issue fetch failed: %s", e)
        return []


def load() -> dict:
    """Return {"text": prompt block, "hide": [substring, ...]}."""
    parts: list[str] = []
    hide: list[str] = []

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

    for issue in _issue_entries():
        body = issue["body"]
        # Strip the pre-filled how-this-was-scored template so only the
        # owner's own notes are injected into scoring prompts.
        if "feed directly into future scoring:" in body:
            body = body.split("feed directly into future scoring:", 1)[1]
        body = re.sub(r"^---\s*$.*", "", body, flags=re.S | re.M)
        body = re.sub(r"^\s*Action:\s*hide\b.*$", "", body, flags=re.I | re.M).strip()
        parts.append(f"[issue] {issue['title']}\n{body}".strip())
        if re.search(r"^\s*Action:\s*hide\b", issue["body"], re.I | re.M):
            target = re.sub(r"^feedback:\s*", "", issue["title"], flags=re.I).strip()
            if target:
                hide.append(target)

    return {"text": "\n\n".join(p for p in parts if p), "hide": hide}


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
            from datetime import datetime, timezone
            rec.setdefault("closed", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            n += 1
    if n:
        log.info("Feedback: hid %d tracked postings", n)
    return n

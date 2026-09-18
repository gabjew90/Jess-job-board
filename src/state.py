"""Seen-postings state: dedupe across runs, committed to the repo as JSON."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Job
from .util import company_key, group_key, source_id, twin_key

STATE_FILE = Path("state/seen_jobs.json")

# Sources whose links die on their own schedule, independent of the
# employer's posting.
AGGREGATOR_SOURCES = {"indeed", "glassdoor", "zip_recruiter", "google"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def prune(state: dict, retention_days: int) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    return {k: v for k, v in state.items() if v.get("first_seen", "9999") >= cutoff}


def unscored_active(state: dict, exclude_ids: set[str]) -> list[str]:
    """Job_ids of active records that never received a score — the residue
    of failed triage chunks. Rescored alongside new jobs each run."""
    return [job_id for job_id, rec in state.items()
            if rec.get("active", True) and "score" not in rec
            and job_id not in exclude_ids]


def split_new(jobs: list[Job], state: dict) -> list[Job]:
    """Return only jobs not already in state, and record them in state.

    State stores metadata (not descriptions) so the dashboard can render
    history without bloating the file.
    """
    # Cross-source twins: same company+title+city under a different location
    # string (Indeed "Herndon, VA" vs Amazon "Herndon, Virginia, USA") is the
    # same posting — never re-alert it, but do borrow missing fields.
    twins = {twin_key(r.get("company", ""), r.get("title", ""), r.get("location", "")): r
             for r in state.values()}
    groups = {group_key(r.get("company", ""), r.get("title", "")): r
              for r in state.values()}
    # Identity by the ATS's own id survives title renames, which otherwise
    # look like "old posting closed, new posting appeared".
    by_source_id = {}
    for r in state.values():
        sid = source_id(r.get("url", ""))
        if sid:
            by_source_id[(company_key(r.get("company", "")), sid)] = r
    new = []
    for job in jobs:
        if job.job_id not in state:
            sid = source_id(job.url)
            twin = (by_source_id.get((company_key(job.company), sid)) if sid else None)
            if twin is not None and twin.get("title") != job.title:
                # Same ATS id, new title: the employer renamed the role.
                twin["title"] = job.title
            twin = twin or (twins.get(twin_key(job.company, job.title, job.location))
                            or groups.get(group_key(job.company, job.title)))
            if twin is not None:
                # Aggregator copies expire independently of the employer's
                # own posting (an Indeed listing went dead while the role
                # was still open on the company board), so when a direct
                # source matches an aggregator record, adopt its link.
                if (twin.get("source") in AGGREGATOR_SOURCES
                        and job.source not in AGGREGATOR_SOURCES):
                    twin["url"] = job.url
                    twin["source"] = job.source
                elif job.source == twin.get("source") and job.url:
                    # The fetcher is authoritative for its own postings, so
                    # link improvements reach records stored earlier.
                    twin["url"] = job.url
                # Record the extra metro on the surviving row instead of
                # alerting the same opening again.
                locs = twin.setdefault("locations", [twin.get("location", "")])
                if job.location and job.location not in locs:
                    locs.append(job.location)
                for field, value in (("date_posted", job.date_posted),
                                     ("pay", job.pay), ("work_mode", job.work_mode)):
                    if value and not twin.get(field):
                        twin[field] = value
                continue
        if job.job_id in state:
            # Backfill fields added after this record was first stored.
            rec = state[job.job_id]
            for field, value in (("date_posted", job.date_posted),
                                 ("pay", job.pay), ("work_mode", job.work_mode)):
                if value and not rec.get(field):
                    rec[field] = value
            continue
        state[job.job_id] = {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "source": job.source,
            "priority": job.priority,
            "first_seen": _today(),
            "first_seen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date_posted": job.date_posted,
            "pay": job.pay,
            "work_mode": job.work_mode,
            "locations": [job.location],
        }
        twins[twin_key(job.company, job.title, job.location)] = state[job.job_id]
        groups[group_key(job.company, job.title)] = state[job.job_id]
        if (sid := source_id(job.url)):
            by_source_id[(company_key(job.company), sid)] = state[job.job_id]
        new.append(job)
    return new

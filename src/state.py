"""Seen-postings state: dedupe across runs, committed to the repo as JSON."""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Job
from .util import AGGREGATOR_SOURCES, company_key, group_key, legacy_text_mode, source_id, twin_key

log = logging.getLogger(__name__)

STATE_FILE = Path("state/seen_jobs.json")


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
    """Drop records closed (or, lacking a date, first seen) before the
    cutoff. Open postings stay however old: dropping one would bring it
    back as new and lose the owner's verdicts on it."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    return {k: v for k, v in state.items()
            if v.get("active", True)
            or str(v.get("closed") or v.get("first_seen", "9999"))[:10] >= cutoff}


# Closed by the owner or a filter rather than by the market. None of these
# may be revived by a fetch or a re-score; lowscore alone may be, when a
# later score or the owner's verdict lifts it.
SUPPRESSED = ("owner_closed", "hidden", "excluded", "duplicate")


def suppressed(rec: dict) -> bool:
    return any(rec.get(k) for k in SUPPRESSED)


def _market_closed(rec: dict) -> bool:
    """Closed because the posting went away, not by the owner or a filter."""
    return not rec.get("active", True) and not rec.get("lowscore") and not suppressed(rec)


def _reopen(rec: dict, job: Job) -> bool:
    """A posting closed on an earlier day that an employer's own board lists
    again is open. Never on an aggregator's word: Indeed keeps listing
    postings whose apply page expiry found gone, and reopening those would
    close them again every next run. Records closed today keep this run's
    closure."""
    from .expiry import ATS_PROVIDERS  # noqa: PLC0415 - expiry imports sources
    # Only full-list boards, whose closure means "missing from a clean
    # fetch": a search-and-probe source (Google, Workday, Microsoft) can
    # list a posting its own probe found gone, and would flap daily.
    if (not _market_closed(rec) or str(rec.get("closed", ""))[:10] >= _today()
            or job.source not in ATS_PROVIDERS):
        return False
    rec["active"] = True
    rec.pop("closed", None)
    rec["reopened"] = _today()
    log.info("State: reopened %s @ %s", rec.get("title"), rec.get("company"))
    return True


def unscored_active(state: dict, exclude_ids: set[str]) -> list[str]:
    """Job_ids of active records that never received a score — the residue
    of failed triage chunks. Rescored alongside new jobs each run."""
    return [job_id for job_id, rec in state.items()
            if rec.get("active", True) and "score" not in rec
            and job_id not in exclude_ids]


def has_range(pay: str) -> bool:
    """'$120,000–$150,000', '$120K-$150K', '$45/hr - $60/hr', '$1 to $2'."""
    return bool(re.search(r"\d\s?[kK]?\s?(?:/\s?\w+\s?)?(?:[-–—]|to)\s?\$?\s?\d", pay or ""))


def _better_pay(field: str, new: str, old: str) -> bool:
    """A range replaces a single figure stored earlier ("$126,000" before
    the minimum/maximum format was read)."""
    return field == "pay" and has_range(new) and not has_range(old)


# Fields a later fetch may fill in or improve on a stored record: filled
# when empty, and pay upgraded from a single figure to a range. Never
# replaced otherwise, so copies of one posting (metros, sources) cannot
# flip the stored value run to run.
MERGE_FIELDS = ("date_posted", "pay", "work_mode", "apply_url")


def _merge_fields(rec: dict, job: Job) -> bool:
    changed = False
    for field in MERGE_FIELDS:
        value = getattr(job, field)
        if value and (not rec.get(field) or _better_pay(field, value, rec[field])):
            rec[field] = value
            changed = True
    return changed


def split_new(jobs: list[Job], state: dict) -> list[Job]:
    """Return only jobs not already in state, and record them in state.

    State stores metadata (not descriptions) so the dashboard can render
    history without bloating the file.
    """
    # Cross-source twins: same company+title+city under a different location
    # string (Indeed "Herndon, VA" vs Amazon "Herndon, Virginia, USA") is the
    # same posting — never re-alert it, but do borrow missing fields.
    # Active records last, so a key shared with an old closed copy maps to
    # the open one: matching the closed one would reopen a duplicate.
    ordered = sorted(state.values(), key=lambda r: bool(r.get("active", True)))
    twins = {twin_key(r.get("company", ""), r.get("title", ""), r.get("location", "")): r
             for r in ordered}
    groups = {group_key(r.get("company", ""), r.get("title", "")): r
              for r in ordered}
    # Identity by the ATS's own id survives title renames, which otherwise
    # look like "old posting closed, new posting appeared".
    by_source_id = {}
    for r in ordered:
        sid = source_id(r.get("url", ""))
        if sid:
            by_source_id[(company_key(r.get("company", "")), sid)] = r
    new = []
    updated = 0
    for job in jobs:
        if job.job_id not in state:
            sid = source_id(job.url)
            twin = (by_source_id.get((company_key(job.company), sid)) if sid else None)
            if twin is not None and twin.get("title") != job.title:
                # Same ATS id, new title: the employer renamed the role.
                twin["title"] = job.title
            twin = twin or (twins.get(twin_key(job.company, job.title, job.location))
                            or groups.get(group_key(job.company, job.title)))
            if twin is not None and twin.get("owner_closed"):
                # The owner closed that one; a relisting is a new opening.
                twin = None
            if twin is not None:
                updated += _reopen(twin, job)
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
                updated += _merge_fields(twin, job)
                continue
        if job.job_id in state:
            rec = state[job.job_id]
            updated += _reopen(rec, job)
            # This posting's own apply link is current, and marked as its
            # own: expiry may close the record when that page is gone, but
            # never on a link borrowed from a twin (fill-only above).
            if job.apply_url and (rec.get("apply_url") != job.apply_url
                                  or not rec.get("apply_url_own")):
                rec.update(apply_url=job.apply_url, apply_url_own=True)
                updated += 1
            # A work mode the posting's own source read from it is recomputed
            # each time that source sees the posting again (the text rules
            # tightened on 2026-10-23). The scorer's reading is kept, and so
            # is a tag reading (scripts/recheck_indeed_work_mode.py) unless
            # the source now gives a mode. A record from before
            # work_mode_by counts as the source's only when the old rules
            # explain its mode; otherwise it was the scorer's.
            if job.source == rec.get("source"):
                by = rec.get("work_mode_by")
                old = rec.get("work_mode", "")
                if by is None and old:
                    by = "fetch" if legacy_text_mode(old, job.description) else "triage"
                    rec["work_mode_by"] = by
                if old != job.work_mode and (by in (None, "", "fetch")
                                             or (by == "tag" and job.work_mode)):
                    rec.update(work_mode=job.work_mode,
                               work_mode_by="fetch" if job.work_mode else "")
                    updated += 1
            # Backfill fields added after this record was first stored.
            updated += _merge_fields(rec, job)
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
            "work_mode_by": "fetch" if job.work_mode else "",
            "apply_url": job.apply_url,
            "apply_url_own": bool(job.apply_url),
            "locations": [job.location],
        }
        twins[twin_key(job.company, job.title, job.location)] = state[job.job_id]
        groups[group_key(job.company, job.title)] = state[job.job_id]
        if (sid := source_id(job.url)):
            by_source_id[(company_key(job.company), sid)] = state[job.job_id]
        new.append(job)
    if updated:
        log.info("State: filled or improved fields on %d tracked record(s)", updated)
    return new

"""Mark tracked postings as closed so the dashboard doesn't link to dead jobs.

A posting closes only when its source says it is gone. Never on a timer: the
30-day age-out this replaced had closed 472 Indeed postings of which two
thirds were still open, while a fifth of the "active" ones had expired.

Two tiers, by how each source can be checked:

1. Full-list sources (greenhouse/lever/ashby boards; radancy/hibob/adp/
   breezy careers sites; the Edged feed): every run fetches the employer's
   FULL posting list, so a tracked posting missing from today's snapshot is
   closed. Exact and free. Skipped for a provider if any of its boards
   failed to fetch this run (otherwise an outage would mass-expire jobs).
2. Keyword-search sources are probed one posting at a time:
   - indeed: the mobile GraphQL API answers jobData(jobKeys) for 500 keys
     per call with an `expired` flag; a key it no longer knows is gone.
   - workday: the CxS job endpoint is 200 for a live posting, 404 for a
     removed one.
   - successfactors: a removed posting redirects to /errorpage/.
   - amazon: the job page is 404 once removed.
   - smartrecruiters: the public postings API is 404 once removed.
   - jibe: the site's own search by req_id returns the posting or nothing.
   - microsoft: the careers SPA serves expired jobs with HTTP 200, but the
     pcsx search API indexes only open positions, so searching for the
     display ID is exact.
   - google-careers: dead postings return a generic 200 page; a live one
     embeds the title.
   A probe closes a posting only on a definitive signal; a network error,
   a 5xx or an unexpected page leaves it open. A source whose probe
   reports most of its postings dead in one run is assumed broken and
   closes nothing that run. Sources without a probe stay open and are
   listed in the log.

Closed records stay in state for dedupe; they never re-alert.
"""
import logging
import re
import time
from datetime import datetime, timezone

import requests

from . import health
from .models import Job
from .util import HEADERS, group_key

log = logging.getLogger(__name__)

# Sources whose fetchers return the complete posting list every run.
ATS_PROVIDERS = ("greenhouse", "lever", "ashby", "radancy", "hibob", "adp", "page",
                 "breezy", "edged")
MS_JOB_API = "https://apply.careers.microsoft.com/api/apply/v2/jobs/{pid}"
MS_SEARCH_API = "https://apply.careers.microsoft.com/api/pcsx/search"
INDEED_API = "https://apis.indeed.com/graphql"
INDEED_BATCH = 500
INDEED_QUERY = ("query JobKeys($keys: [ID!]!) { jobData(input: {jobKeys: $keys})"
                " { results { job { key expired } } } }")
WORKDAY_URL = re.compile(r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/"
                         r"(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/job/(.+)$")
INDEED_KEY = re.compile(r"[?&]jk=([0-9a-f]{16})")
# A probe that finds more than this share of a source dead in one run is
# treated as broken (site change, block) and closes nothing for that source.
SUSPECT_DEAD_SHARE = 0.5
SUSPECT_MIN = 20


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _close(rec: dict) -> None:
    rec["active"] = False
    rec["closed"] = _today()


def _healthy_ats_providers() -> set[str]:
    """Providers whose boards ALL fetched cleanly this run."""
    by_provider: dict[str, list[bool]] = {}
    for source, entry in health._current.items():
        provider = source.split(":")[0]
        if provider in ATS_PROVIDERS:
            by_provider.setdefault(provider, []).append(entry["ok"])
    return {p for p, oks in by_provider.items() if oks and all(oks)}


def _google_alive(url: str, title: str) -> bool | None:
    """Dead Google postings still return 200 with a generic page; a live one
    embeds the job title in the server-rendered HTML."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            return False
        if resp.status_code != 200 or len(title) < 8:
            return None
        return title[:25].lower() in resp.text.lower()
    except Exception as e:  # noqa: BLE001
        log.debug("google liveness check failed for %s: %s", url, e)
        return None


def _microsoft_alive(url: str) -> bool | None:
    """True/False when determinable, None on any doubt."""
    try:
        pid = url.rstrip("/").split("/")[-1]
        job = requests.get(MS_JOB_API.format(pid=pid),
                           params={"domain": "microsoft.com"},
                           headers=HEADERS, timeout=20).json()
        display_id = str(job.get("display_job_id") or "")
        if not display_id:
            return None
        time.sleep(0.3)
        found = requests.get(MS_SEARCH_API,
                             params={"domain": "microsoft.com",
                                     "query": display_id, "num": 5},
                             headers=HEADERS, timeout=20).json()
        positions = found.get("data", {}).get("positions", [])
        return any(str(p.get("displayJobId")) == display_id for p in positions)
    except Exception as e:  # noqa: BLE001
        log.debug("microsoft liveness check failed for %s: %s", url, e)
        return None


def _workday_alive(url: str) -> bool | None:
    m = WORKDAY_URL.match(url)
    if not m:
        return None
    tenant, wd, site, path = m.groups()
    try:
        resp = requests.get(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{path}",
                            headers={**HEADERS, "Accept": "application/json"}, timeout=20)
        if resp.status_code == 404:
            return False
        return True if resp.status_code == 200 else None
    except Exception as e:  # noqa: BLE001
        log.debug("workday liveness check failed for %s: %s", url, e)
        return None


def _successfactors_alive(url: str) -> bool | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if "/errorpage" in resp.url:
            return False
        return True if resp.status_code == 200 else None
    except Exception as e:  # noqa: BLE001
        log.debug("successfactors liveness check failed for %s: %s", url, e)
        return None


def _status_alive(url: str, headers: dict | None = None) -> bool | None:
    """For sites whose removed postings answer 404 (amazon.jobs, the
    SmartRecruiters postings API)."""
    try:
        resp = requests.get(url, headers={**HEADERS, **(headers or {})}, timeout=20)
        if resp.status_code == 404:
            return False
        return True if resp.status_code == 200 else None
    except Exception as e:  # noqa: BLE001
        log.debug("liveness check failed for %s: %s", url, e)
        return None


def _smartrecruiters_alive(url: str) -> bool | None:
    m = re.match(r"https://jobs\.smartrecruiters\.com/([^/]+)/(\d+)", url)
    if not m:
        return None
    return _status_alive(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}")


def _jibe_alive(url: str) -> bool | None:
    """Jibe's search is fuzzy, so a hit counts only when its req_id matches."""
    m = re.match(r"(https://[^/]+)/careers-home/jobs/([^/?]+)", url)
    if not m:
        return None
    base, req_id = m.groups()
    try:
        resp = requests.get(f"{base}/api/jobs", headers={**HEADERS, "Accept": "application/json"},
                            params={"keywords": req_id, "page": 1, "limit": 10, "internal": "false"},
                            timeout=20)
        if resp.status_code != 200:
            return None
        jobs = resp.json().get("jobs") or []
        return any(str((j.get("data") or {}).get("req_id")) == req_id for j in jobs)
    except Exception as e:  # noqa: BLE001
        log.debug("jibe liveness check failed for %s: %s", url, e)
        return None


def _indeed_expired(keys: list[str]) -> dict[str, bool] | None:
    """{key: expired} for every key the API still knows. None when the API
    is unavailable (jobspy not installed, HTTP error, GraphQL error) so the
    caller leaves everything open."""
    try:
        from jobspy.indeed.constant import api_headers  # noqa: PLC0415 - optional dep
    except ImportError:
        log.warning("jobspy not installed; Indeed liveness probe skipped")
        return None
    headers = {**api_headers, "indeed-co": "US"}
    out: dict[str, bool] = {}
    for i in range(0, len(keys), INDEED_BATCH):
        batch = keys[i:i + INDEED_BATCH]
        try:
            resp = requests.post(INDEED_API, headers=headers, timeout=60,
                                 json={"query": INDEED_QUERY, "variables": {"keys": batch}})
            payload = resp.json()
            if resp.status_code != 200 or payload.get("errors"):
                log.warning("Indeed liveness probe failed: %s %s", resp.status_code,
                            str(payload.get("errors", ""))[:200])
                return None
            for item in payload["data"]["jobData"]["results"]:
                job = item.get("job") or {}
                if job.get("key"):
                    out[job["key"]] = bool(job.get("expired"))
        except Exception as e:  # noqa: BLE001
            log.warning("Indeed liveness probe failed: %s", e)
            return None
        time.sleep(0.5)
    return out


# Per-posting probes: True alive, False definitively gone, None unknown.
PROBES = {
    "microsoft": lambda rec: _microsoft_alive(rec.get("url", "")),
    "google-careers": lambda rec: _google_alive(rec.get("url", ""), rec.get("title", "")),
    "workday": lambda rec: _workday_alive(rec.get("url", "")),
    "successfactors": lambda rec: _successfactors_alive(rec.get("url", "")),
    "amazon": lambda rec: _status_alive(rec.get("url", "")),
    "smartrecruiters": lambda rec: _smartrecruiters_alive(rec.get("url", "")),
    "jibe": lambda rec: _jibe_alive(rec.get("url", "")),
}


def probe_dead(records: dict[str, dict]) -> dict[str, set[str]]:
    """{source: job_ids found dead} for the given active records, using the
    Indeed batch API and the per-posting probes. Records from sources with
    no probe are left alone and named in the log."""
    by_source: dict[str, dict[str, dict]] = {}
    for job_id, rec in records.items():
        by_source.setdefault(rec.get("source", ""), {})[job_id] = rec

    dead: dict[str, set[str]] = {}
    if "indeed" in by_source:
        keyed = {jid: INDEED_KEY.search(rec.get("url", "")) for jid, rec in by_source["indeed"].items()}
        keyed = {jid: m.group(1) for jid, m in keyed.items() if m}
        verdict = _indeed_expired(sorted(set(keyed.values()))) if keyed else {}
        if verdict is not None:
            dead["indeed"] = {jid for jid, key in keyed.items()
                              if key not in verdict or verdict[key]}
    for source, recs in by_source.items():
        probe = PROBES.get(source)
        if source == "indeed" or source in ATS_PROVIDERS:
            continue
        if probe is None:
            log.info("No liveness probe for source %r: %d posting(s) stay open",
                     source, len(recs))
            continue
        found = set()
        for jid, rec in recs.items():
            time.sleep(0.3)
            if probe(rec) is False:
                found.add(jid)
        dead[source] = found

    for source, found in list(dead.items()):
        total = len(by_source[source])
        if len(found) >= SUSPECT_MIN and len(found) / total > SUSPECT_DEAD_SHARE:
            log.warning("PROBE SUSPECT %s: %d of %d reported dead; closing none this run",
                        source, len(found), total)
            dead[source] = set()
    return dead


def sweep(seen: dict, raw_jobs: list[Job], config: dict) -> list[dict]:
    """Mark closed postings inactive in-place. Returns the records closed."""
    closed: list[dict] = []
    present = {j.job_id for j in raw_jobs}
    present_groups = {group_key(j.company, j.title) for j in raw_jobs}
    healthy = _healthy_ats_providers()

    to_probe: dict[str, dict] = {}
    for job_id, rec in seen.items():
        if not rec.get("active", True):
            continue
        source = rec.get("source", "")
        if source in ATS_PROVIDERS:
            if (source in healthy and job_id not in present
                    and group_key(rec.get("company", ""),
                                  rec.get("title", "")) not in present_groups):
                _close(rec)
                closed.append(rec)
        else:
            to_probe[job_id] = rec

    dead = probe_dead(to_probe)
    for source, ids in dead.items():
        for job_id in ids:
            _close(seen[job_id])
            closed.append(seen[job_id])

    if closed:
        log.info("Expiry sweep: closed %d postings (%s)", len(closed),
                 ", ".join(f"{s} {len(ids)}" for s, ids in sorted(dead.items()) if ids) or "snapshot diff")
    return closed

"""Workday CxS fetcher — covers the many companies on Workday recruiting
(NVIDIA, AMD, most utilities). Public JSON API, no auth:

  POST https://{host}/wday/cxs/{tenant}/{site}/jobs
       {"searchText": ..., "limit": 20, "offset": 0, "appliedFacets": {}}

Search results carry no descriptions (title-based filtering applies, like
Microsoft before enrichment). Boards live in config "workday_boards"; find a
company's host/tenant/site from its careers URL:
https://{tenant}.wdN.myworkdayjobs.com/{site}
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from .. import health
from ..models import Job
from ..util import HEADERS

log = logging.getLogger(__name__)

RESULTS_PER_TERM = 20


def posted_date(posted_on: str) -> str:
    """Workday states age, not a date: "Posted Today", "Posted Yesterday",
    "Posted 3 Days Ago". "Posted 30+ Days Ago" gives no date, so it stays
    blank rather than inventing one."""
    text = (posted_on or "").lower()
    if "30+" in text:
        return ""
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        m = re.search(r"(\d+)\s+days?\s+ago", text)
        if not m:
            return ""
        days = int(m.group(1))
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


FACET_CAP = 1500   # postings per facet set, a guard against a runaway board


def _job(board: dict, p: dict, company: str) -> Job:
    return Job(
        title=p.get("title", ""),
        company=company,
        location=p.get("locationsText", ""),
        url=f"https://{board['host']}/en-US/{board['site']}{p.get('externalPath', '')}",
        source="workday",
        date_posted=posted_date(p.get("postedOn", "")),
    )


def fetch_facets(board: dict) -> list[Job]:
    """Every posting under each of the board's facet sets, instead of the
    top 20 per search term: for an employer watched closely (Flex and its
    Axiom spin-off). Each set is {"facets": {facetParameter: [ids]},
    "company": optional name}; facet ids come from the "facets" block of
    any search response, and several parameters in one set must all match.
    A posting in several sets keeps the first set's company, so list the
    narrow sets (a spin-off's brand) first. Name a unit "Flex (Axiom)":
    the key that dedupes postings ignores the bracket, so the unit's
    postings still match ones stored as "Flex".

    A set that fails (a facet id Workday no longer knows answers 400) is
    logged and skipped; the board fails only when every set does."""
    url = f"https://{board['host']}/wday/cxs/{board['tenant']}/{board['site']}/jobs"
    by_path: dict[str, Job] = {}
    errors = []
    for fs in board["facet_sets"]:
        company = fs.get("company") or board["company"]
        offset, total = 0, None
        try:
            while True:
                resp = requests.post(url, headers={**HEADERS, "Accept": "application/json"},
                                     json={"searchText": "", "limit": RESULTS_PER_TERM,
                                           "offset": offset, "appliedFacets": fs["facets"]},
                                     timeout=30)
                resp.raise_for_status()
                data = resp.json()
                page = data.get("jobPostings", [])
                for p in page:
                    by_path.setdefault(p.get("externalPath", ""), _job(board, p, company))
                if total is None:   # Workday reports the total on the first page only
                    total = data.get("total", 0)
                offset += RESULTS_PER_TERM
                if not page or offset >= total:
                    break
                if offset >= FACET_CAP:
                    log.warning("workday:%s %s: stopped at %d of %d postings",
                                board["tenant"], company, FACET_CAP, total)
                    break
                time.sleep(0.5)
        except Exception as e:  # noqa: BLE001 - one stale facet must not cost the others
            log.warning("workday:%s facet set %s failed: %s", board["tenant"], fs["facets"], e)
            errors.append(e)
    if errors and len(errors) == len(board["facet_sets"]):
        raise errors[0]
    # Deduped by posting path above (a job_id carries the company, which
    # differs between sets); by job_id here, as fetch_board does.
    return list({j.job_id: j for j in reversed(list(by_path.values()))}.values())


def fetch_board(board: dict, terms: list[str]) -> list[Job]:
    if board.get("facet_sets"):
        return fetch_facets(board)
    url = f"https://{board['host']}/wday/cxs/{board['tenant']}/{board['site']}/jobs"
    jobs: dict[str, Job] = {}
    for term in terms:
        resp = requests.post(url, headers={**HEADERS, "Accept": "application/json"},
                             json={"searchText": term, "limit": RESULTS_PER_TERM,
                                   "offset": 0, "appliedFacets": {}}, timeout=30)
        resp.raise_for_status()
        for p in resp.json().get("jobPostings", []):
            job = _job(board, p, board["company"])
            jobs[job.job_id] = job
        time.sleep(1)
    return list(jobs.values())


def fetch(config: dict) -> list[Job]:
    out: list[Job] = []
    for board in config.get("workday_boards", []):
        label = f"workday:{board['tenant']}"
        try:
            got = fetch_board(board, board.get("terms") or config["search_terms"])
            out.extend(got)
            log.info("%s: %d postings", label, len(got))
            health.record(label, ok=True, count=len(got))
        except Exception as e:  # noqa: BLE001 - per-source isolation by design
            log.warning("SOURCE FAILURE %s: %s", label, e)
            health.record(label, ok=False, error=e)
    return out

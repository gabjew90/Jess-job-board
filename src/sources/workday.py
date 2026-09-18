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
import time

import requests

from .. import health
from ..models import Job
from ..util import HEADERS

log = logging.getLogger(__name__)

RESULTS_PER_TERM = 20


def fetch_board(board: dict, terms: list[str]) -> list[Job]:
    url = f"https://{board['host']}/wday/cxs/{board['tenant']}/{board['site']}/jobs"
    jobs: dict[str, Job] = {}
    for term in terms:
        resp = requests.post(url, headers={**HEADERS, "Accept": "application/json"},
                             json={"searchText": term, "limit": RESULTS_PER_TERM,
                                   "offset": 0, "appliedFacets": {}}, timeout=30)
        resp.raise_for_status()
        for p in resp.json().get("jobPostings", []):
            path = p.get("externalPath", "")
            job = Job(
                title=p.get("title", ""),
                company=board["company"],
                location=p.get("locationsText", ""),
                url=f"https://{board['host']}/en-US/{board['site']}{path}",
                source="workday",
            )
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

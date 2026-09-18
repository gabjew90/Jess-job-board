"""SAP SuccessFactors career-site fetcher (PG&E, NextEra, and most large
utilities). These sites are server-rendered ("Career Site Builder"):

  GET {base}/search/?q={term}&startrow=0

returns HTML rows with anchors class="jobTitle-link" (href /job/<slug>/<id>/)
plus jobLocation/jobDate spans in row order. No descriptions in search
results — filtering is title-based. Boards live in config
"successfactors_boards": [{"base": ..., "company": ...}].
"""
import logging
import re
import time

import requests

from .. import health
from ..models import Job
from ..util import HEADERS, extract_pay, infer_work_mode, strip_html

log = logging.getLogger(__name__)

_desc_cache: dict = {}


def _description(url: str) -> str:
    """Search tiles carry no description; fetch the job page once per run.
    Without this, utility roles are scored on title alone — and PG&E is a
    primary target employer."""
    if url not in _desc_cache:
        try:
            time.sleep(0.3)
            html = requests.get(url, headers=HEADERS, timeout=25).text
            # The posting body sits in the jobDescription block on CSB pages.
            m = re.search(r'class="jobDescription"(.*?)(?:class="jobShare"|</main>)',
                          html, re.S)
            _desc_cache[url] = strip_html(m.group(1) if m else html)[:6000]
        except Exception as e:  # noqa: BLE001
            log.debug("successfactors description fetch failed for %s: %s", url, e)
            _desc_cache[url] = ""
    return _desc_cache[url]


TILE_RE = re.compile(
    r'<a[^>]*class="jobTitle-link"[^>]*href="([^"]+)"[^>]*>\s*([^<]+)', re.S)
LOC_RE = re.compile(r'class="jobLocation"[^>]*>\s*([^<]+)', re.S)
DATE_RE = re.compile(r'class="jobDate[^"]*"[^>]*>\s*([^<]+)', re.S)


def fetch_board(board: dict, terms: list[str]) -> list[Job]:
    jobs: dict[str, Job] = {}
    for term in terms:
        resp = requests.get(f"{board['base']}/search/",
                            params={"q": term, "sortColumn": "referencedate",
                                    "sortDirection": "desc"},
                            headers=HEADERS, timeout=30)
        resp.raise_for_status()
        tiles = TILE_RE.findall(resp.text)
        locations = [x.strip() for x in LOC_RE.findall(resp.text)]
        dates = [x.strip() for x in DATE_RE.findall(resp.text)]
        for i, (href, title) in enumerate(tiles):
            url = board["base"] + href.split("?")[0]
            title = title.strip()
            location = locations[i] if i < len(locations) else ""
            desc = _description(url)
            job = Job(
                title=title,
                company=board["company"],
                location=location,
                url=url,
                source="successfactors",
                description=desc,
                date_posted=_iso(dates[i]) if i < len(dates) else "",
                pay=extract_pay(desc),
                work_mode=infer_work_mode(title, location, desc),
            )
            jobs[job.job_id] = job
        time.sleep(1)
    return list(jobs.values())


def _iso(text: str) -> str:
    from datetime import datetime
    for fmt in ("%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text.strip()


def fetch(config: dict) -> list[Job]:
    out: list[Job] = []
    for board in config.get("successfactors_boards", []):
        label = f"successfactors:{board['company']}"
        try:
            got = fetch_board(board, config["search_terms"])
            out.extend(got)
            log.info("%s: %d postings", label, len(got))
            health.record(label, ok=True, count=len(got))
        except Exception as e:  # noqa: BLE001 - per-source isolation by design
            log.warning("SOURCE FAILURE %s: %s", label, e)
            health.record(label, ok=False, error=e)
    return out

"""ATS board fetchers: Greenhouse, Lever, Ashby public JSON APIs.

The most reliable source type — documented-ish endpoints that never block.
Boards are listed in config.json "ats_boards"; each entry fetches the
company's FULL posting list and relies on the keyword filter to trim.

Finding a company's slug: check their careers page URL or probe
  https://boards-api.greenhouse.io/v1/boards/<slug>/jobs
  https://api.lever.co/v0/postings/<slug>?mode=json
  https://api.ashbyhq.com/posting-api/job-board/<slug>
"""
import logging
import time
from datetime import datetime, timezone

import requests

from .. import health
from ..models import Job
from ..util import HEADERS, extract_pay, infer_work_mode, strip_html

log = logging.getLogger(__name__)


def fetch_greenhouse(board: str, company: str) -> list[Job]:
    resp = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
        params={"content": "true"}, headers=HEADERS, timeout=30,
    )
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs") or []:
        desc = strip_html(j.get("content", ""))
        title = j.get("title", "")
        location = (j.get("location") or {}).get("name", "")
        # Companies that EMBED the board publish an absolute_url like
        # "https://acme.com/careers/?gh_jid=123", which lands on the careers
        # index rather than the posting. The canonical board URL deep links.
        url = j.get("absolute_url", "")
        if "gh_jid=" in url or not url:
            url = f"https://job-boards.greenhouse.io/{board}/jobs/{j.get('id')}"
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source="greenhouse",
            description=desc,
            date_posted=(j.get("updated_at") or "")[:10],
            pay=extract_pay(desc),
            work_mode=infer_work_mode(title, location, desc),
        ))
    return jobs


def fetch_lever(board: str, company: str) -> list[Job]:
    resp = requests.get(
        f"https://api.lever.co/v0/postings/{board}",
        params={"mode": "json"}, headers=HEADERS, timeout=30,
    )
    resp.raise_for_status()
    jobs = []
    for j in resp.json() or []:
        desc = strip_html(j.get("descriptionPlain") or j.get("description", ""))
        title = j.get("text", "")
        location = (j.get("categories") or {}).get("location", "")
        rng = j.get("salaryRange") or {}
        if rng.get("min") and rng.get("max"):
            unit = "yr" if "year" in str(rng.get("interval", "")) else "hr"
            pay = f"${rng['min']:,.0f}–${rng['max']:,.0f}/{unit}"
        else:
            pay = extract_pay(desc)
        created = j.get("createdAt")
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=j.get("hostedUrl", ""),
            source="lever",
            description=desc,
            date_posted=datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else "",
            pay=pay,
            work_mode=j.get("workplaceType") or infer_work_mode(title, location, desc),
        ))
    return jobs


def fetch_ashby(board: str, company: str) -> list[Job]:
    resp = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{board}",
        params={"includeCompensation": "true"}, headers=HEADERS, timeout=30,
    )
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs") or []:
        desc = strip_html(j.get("descriptionPlain") or j.get("descriptionHtml", ""))
        title = j.get("title", "")
        location = j.get("location", "")
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=j.get("jobUrl", ""),
            source="ashby",
            description=desc,
            date_posted=(j.get("publishedAt") or "")[:10],
            pay=comp.replace("•", "·") or extract_pay(desc),
            work_mode="remote" if j.get("isRemote") else infer_work_mode(title, location, desc),
        ))
    return jobs


def _flatten(value) -> str:
    """API text fields arrive as str OR list of bullets; str() on a list
    would inject Python repr (brackets, quotes) into descriptions."""
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return str(value or "")


def fetch_edged(board: str, company: str) -> list[Job]:
    """Edged/Endeavour/ThermalWorks aggregate API (jobs-central). Origin-
    gated: send the careers page's Origin/Referer. Company comes from each
    job, not the config entry. Rich fields incl. salary and full text.

    `board` selects the company filter the API supports (use "all" for the
    whole feed) so multiple entries can't silently refetch the same rows.
    """
    jobs = []
    page = 1
    while True:
        params = {"per_page": 100, "page": page}
        if board and board not in ("all", "jobs-central"):
            params["company"] = board
        resp = requests.get(
            "https://jobs-central.laravel.cloud/api/v1/jobs",
            params=params,
            headers={**HEADERS, "Accept": "application/json",
                     "Referer": "https://edged.us/careers",
                     "Origin": "https://edged.us"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        for j in payload.get("data", []):
            if j.get("isActive") is False:
                continue
            # `requirements`/`benefits` on this feed carry EEO and benefits
            # boilerplate, not role content; `description` is comprehensive.
            desc = strip_html(_flatten(j.get("description"))
                              or _flatten(j.get("summary")))
            title = j.get("title", "")
            location = j.get("location", "")
            lo, hi = j.get("salaryMin"), j.get("salaryMax")
            if lo and hi:
                unit = "hr" if float(hi) < 2000 else "yr"
                cur = "" if (j.get("currency") or "USD") == "USD" else f" {j['currency']}"
                pay = f"${float(lo):,.0f}–${float(hi):,.0f}/{unit}{cur}"
            else:
                pay = extract_pay(desc)
            jobs.append(Job(
                title=title,
                company=j.get("company") or company,
                location=location,
                url=j.get("externalUrl") or "https://edged.us/careers",
                source="edged",
                description=desc,
                date_posted=(j.get("postedDate") or "")[:10],
                pay=pay,
                work_mode=infer_work_mode(title, location, desc),
            ))
        pages = (payload.get("pagination") or {}).get("last_page", 1)
        if page >= pages:
            break
        page += 1
        time.sleep(0.5)
    return jobs


PROVIDERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "edged": fetch_edged,
}


def fetch(config: dict) -> list[Job]:
    jobs: list[Job] = []
    for entry in config.get("ats_boards", []):
        provider, board, company = entry["provider"], entry["board"], entry["company"]
        try:
            got = PROVIDERS[provider](board, company)
            jobs.extend(got)
            log.info("%s / %s: %d postings", provider, board, len(got))
            health.record(f"{provider}:{board}", ok=True, count=len(got))
        except Exception as e:  # noqa: BLE001 - per-source isolation by design
            log.warning("SOURCE FAILURE %s / %s: %s", provider, board, e)
            health.record(f"{provider}:{board}", ok=False, error=e)
        time.sleep(1)
    return jobs

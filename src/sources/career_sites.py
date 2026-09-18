"""Employer careers sites that render in JavaScript but are fed by public
JSON endpoints — the vendor platforms behind them:

- radancy  (jobsapi-google.m-cloud.io; Southern California Edison and many
           large employers on Radancy/"CWS" WordPress career sites)
- hibob    ({slug}.careers.hibob.com; IREN)
- adp      (ADP WorkforceNow recruitment; Applied Digital)
- jibe     (Jibe/iCIMS careers sites; AMD)

None of these pages carry postings in their HTML, so `requests` against the
page sees nothing and Indeed was the only path to them. Each endpoint here
was found by loading the careers page in headless Chromium and capturing
the JSON calls it makes (scripts/probe_careers_site.js). The pipeline itself
needs no browser: once the endpoint is known, plain HTTP fetches it.

radancy, hibob and adp return the employer's FULL posting list, so the
expiry sweep snapshot-diffs them exactly (see expiry.ATS_PROVIDERS). jibe is
a keyword search (thousands of postings per employer), so it runs per search
term like Workday and expires by age.

Config "career_sites": one entry per employer —
  {"provider": "radancy", "company": ..., "tenant": <companyName uuid>}
  {"provider": "hibob",   "company": ..., "slug": <subdomain>}
  {"provider": "adp",     "company": ..., "cid": ..., "ccId": ...}
  {"provider": "jibe",    "company": ..., "base": "https://careers.x.com"}
Optional "keep_all": true bypasses the keyword filter (mission-pure employers).
"""
import logging
import re
import time

import requests

from .. import health
from ..models import Job
from ..util import HEADERS, extract_pay, infer_work_mode, strip_html

log = logging.getLogger(__name__)

PAGE = 100
RADANCY_URL = "https://jobsapi-google.m-cloud.io/api/job/search"
ADP_API = ("https://workforcenow.adp.com/mascsr/default/careercenter/public/"
           "events/staffing/v1/job-requisitions")
ADP_PAGE = ("https://workforcenow.adp.com/mascsr/default/mdf/recruitment/"
            "recruitment.html")

_MODE = {"hybrid": "hybrid", "remote": "remote", "onsite": "onsite",
         "on site": "onsite", "on-site": "onsite"}


def _mode(value: str, title: str, location: str, desc: str) -> str:
    """Structured work-mode field when present, else text inference."""
    return _MODE.get((value or "").strip().lower()) or infer_work_mode(title, location, desc)


def _range(lo, hi, unit: str, currency: str = "") -> str:
    try:
        cur = "" if currency in ("", "USD") else f" {currency}"
        return f"${float(lo):,.0f}–${float(hi):,.0f}/{unit}{cur}"
    except (TypeError, ValueError):
        return ""


def _range_from_text(text: str) -> str:
    """'$161,700 - $242,600' / '$22.50 - $30.00' → project range format,
    unit by magnitude (hourly figures are always well under 2,000)."""
    nums = re.findall(r"\$\s?([\d,]+(?:\.\d+)?)", text or "")
    if len(nums) != 2:
        return ""
    lo, hi = (float(n.replace(",", "")) for n in nums)
    return _range(lo, hi, "hr" if hi < 2000 else "yr")


def fetch_radancy(entry: dict, terms: list[str]) -> list[Job]:
    """Full list. `tenant` is the uuid in the site's companyName parameter
    (`companies/<uuid>`), visible in the search page's API calls.
    Sorted by publish time so offset paging is stable; an incomplete
    snapshot raises so the expiry sweep will not treat missing jobs as closed.
    """
    company_name = f"companies/{entry['tenant']}"
    jobs: dict[str, Job] = {}
    seen_ids: set = set()
    offset, total = 0, None
    while True:
        resp = requests.get(RADANCY_URL, headers=HEADERS, timeout=30, params={
            "pageSize": PAGE, "offset": offset, "companyName": company_name,
            "query": "", "orderBy": "posting_publish_time desc",
        })
        resp.raise_for_status()
        payload = resp.json()
        # Judge completeness against the FIRST page's total: a posting
        # published mid-crawl shifts later pages by one row (a duplicate,
        # harmless) and bumps the reported total, which must not read as a
        # failed snapshot. A posting removed mid-crawl still trips the check.
        if total is None:
            total = payload.get("totalHits", 0)
        results = payload.get("searchResults") or []
        for r in results:
            j = r.get("job") or {}
            seen_ids.add(j.get("id"))
            desc = strip_html(j.get("description", ""))
            title = j.get("title", "")
            location = ", ".join(x for x in (j.get("primary_city"), j.get("primary_state")) if x)
            job = Job(
                title=title,
                # `brand` is the hiring entity on multi-brand sites (Southern
                # California Edison vs Edison International).
                company=j.get("brand") or entry["company"],
                location=location,
                url=j.get("url") or entry.get("site", ""),
                source="radancy",
                description=desc,
                date_posted=(j.get("open_date") or "")[:10],
                pay=_range_from_text(j.get("salary") or "") or extract_pay(desc),
                work_mode=_mode(j.get("location_type"), title, location, desc),
            )
            jobs[job.job_id] = job
        offset += len(results)
        if not results or offset >= total:
            break
        time.sleep(0.5)
    if len(seen_ids) < total:
        raise RuntimeError(f"incomplete snapshot: {len(seen_ids)} of {total} postings")
    return list(jobs.values())


def fetch_hibob(entry: dict, terms: list[str]) -> list[Job]:
    """Full list. The feed answers 401 without the career site as Referer."""
    base = f"https://{entry['slug']}.careers.hibob.com"
    resp = requests.get(f"{base}/api/job-ad", timeout=30,
                        headers={**HEADERS, "Accept": "application/json",
                                 "Referer": f"{base}/jobs"})
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobAdDetails") or []:
        # `benefits` is company-wide boilerplate; the other three sections
        # describe the role.
        desc = strip_html(" ".join(j.get(k) or "" for k in
                                   ("description", "responsibilities", "requirements")))
        title = j.get("title", "")
        location = j.get("site", "")
        lo, hi = j.get("payTransparencyMinSalary"), j.get("payTransparencyMaxSalary")
        period = (j.get("payTransparencySalaryPayPeriod") or "").lower()
        pay = (_range(lo, hi, "hr" if "hour" in period else "yr",
                      j.get("payTransparencySalaryCurrency") or "")
               if lo and hi else extract_pay(desc))
        jobs.append(Job(
            title=title,
            company=entry["company"],
            location=location,
            url=f"{base}/jobs/{j.get('id')}",
            source="hibob",
            description=desc,
            date_posted=(j.get("publishedAt") or "")[:10],
            pay=pay,
            work_mode=_mode(j.get("workspaceType"), title, location, desc),
        ))
    return jobs


def fetch_adp(entry: dict, terms: list[str]) -> list[Job]:
    """Full list; descriptions come from a per-requisition call. `cid` and
    `ccId` are the parameters of the employer's recruitment.html URL."""
    common = {"cid": entry["cid"], "ccId": entry["ccId"], "lang": "en_US"}
    reqs = []
    skip = 0
    while True:
        resp = requests.get(ADP_API, headers={**HEADERS, "Accept": "application/json"},
                            params={**common, "$top": PAGE, "$skip": skip}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        page = payload.get("jobRequisitions") or []
        reqs.extend(page)
        total = (payload.get("meta") or {}).get("totalNumber", len(reqs))
        skip += len(page)
        if not page or skip >= total:
            break
    jobs = []
    for r in reqs:
        item = r.get("itemID", "")
        desc = ""
        try:
            time.sleep(0.3)
            detail = requests.get(f"{ADP_API}/{item}", params=common, timeout=25,
                                  headers={**HEADERS, "Accept": "application/json"}).json()
            desc = strip_html((detail or {}).get("requisitionDescription", ""))
        except Exception as e:  # noqa: BLE001 - a missing description is not fatal
            log.debug("adp detail fetch failed for %s: %s", item, e)
        title = r.get("requisitionTitle", "")
        locs = r.get("requisitionLocations") or [{}]
        location = ((locs[0].get("nameCode") or {}).get("shortName") or "").strip()
        jobs.append(Job(
            title=title,
            company=entry["company"],
            location=location,
            url=f"{ADP_PAGE}?cid={entry['cid']}&ccId={entry['ccId']}&lang=en_US&jobId={item}",
            source="adp",
            description=desc,
            date_posted=(r.get("postDate") or "")[:10],
            pay=extract_pay(desc),
            work_mode=infer_work_mode(title, location, desc),
        ))
    return jobs


def _jibe_pay(data: dict) -> str:
    """AMD publishes the range as two tag fields ("USD $161,210.00/Yr.");
    generic enough to try, extract_pay on the text is the fallback."""
    amounts, currency = [], ""
    for key in ("tags2", "tags3"):
        for tag in data.get(key) or []:
            m = re.search(r"\$\s?([\d,]+)", str(tag))
            if m:
                amounts.append(m.group(1).replace(",", ""))
                # Non-US postings quote local currency with a "$" sign
                # ("TWD NT$2,433,060.00/Yr."): keep the code visible.
                code = re.match(r"\s*([A-Z]{3})\b", str(tag))
                currency = currency or (code.group(1) if code else "")
    if len(amounts) == 2 and amounts[0] != amounts[1]:
        unit = "hr" if "hr" in str(data.get("tags2")).lower() else "yr"
        return _range(amounts[0], amounts[1], unit, currency)
    return ""


def fetch_jibe(entry: dict, terms: list[str]) -> list[Job]:
    """Keyword search per term (full-text over descriptions). `base` is the
    careers host; postings deep-link to /careers-home/jobs/<req_id>."""
    base = entry["base"].rstrip("/")
    jobs: dict[str, Job] = {}
    for term in terms:
        resp = requests.get(f"{base}/api/jobs", headers={**HEADERS, "Accept": "application/json"},
                            params={"keywords": term, "page": 1, "limit": PAGE,
                                    "sortBy": "relevance", "descending": "false",
                                    "internal": "false"}, timeout=30)
        resp.raise_for_status()
        for j in resp.json().get("jobs") or []:
            d = j.get("data") or {}
            desc = strip_html(d.get("description", ""))
            for extra in ("responsibilities", "qualifications"):
                text = strip_html(d.get(extra) or "")
                if text and text[:80] not in desc:
                    desc += " " + text
            title = d.get("title", "")
            location = d.get("full_location") or d.get("location_name", "")
            job = Job(
                title=title,
                company=entry["company"],
                location=location,
                url=f"{base}/careers-home/jobs/{d.get('req_id') or d.get('slug')}?lang=en-us",
                source="jibe",
                description=desc,
                date_posted=(d.get("posted_date") or "")[:10],
                pay=_jibe_pay(d) or extract_pay(desc),
                work_mode=infer_work_mode(title, location, desc),
            )
            jobs[job.job_id] = job
        time.sleep(1)
    return list(jobs.values())


def fetch_page(entry: dict, terms: list[str]) -> list[Job]:
    """A careers page that lists its openings as plain HTML with no ATS
    behind it (Flux Power's HubSpot page: an <h4> title, a <p> with type
    and location, and a link to a PDF job description). Config:

      {"provider": "page", "company": "Flux Power",
       "url": "https://www.fluxpower.com/careers",
       "title_pattern": "<h4[^>]*>(.*?)</h4>",          # group 1 = title
       "location_pattern": "^\\s*<p>(.*?)</p>",           # optional, group 1
       "link_pattern": "href=\"([^\"]+\\.pdf)\""}       # optional, group 1

    Every match of title_pattern is a posting; the location and link
    patterns are searched in the HTML that follows each title, up to the
    next title. When link_pattern is set, a title with no link is skipped
    (perk headings on the same page). Descriptions are the title only (a linked PDF is not
    fetched), so the title screen does the filtering. Full-list: the
    expiry pass snapshot-diffs it like an ATS board."""
    resp = requests.get(entry["url"], headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text
    titles = list(re.finditer(entry["title_pattern"], html, re.S | re.I))
    jobs: dict[str, Job] = {}
    for i, m in enumerate(titles):
        title = strip_html(m.group(1)).strip()
        if not title or len(title) > 120:
            continue
        chunk = html[m.end():titles[i + 1].start() if i + 1 < len(titles) else m.end() + 3000]
        location = ""
        if entry.get("location_pattern"):
            lm = re.search(entry["location_pattern"], chunk, re.S | re.I)
            if lm:
                location = strip_html(lm.group(1)).strip()
                location = re.sub(r"^(full|part)[ -]time\s*[-–:]?\s*", "", location, flags=re.I).strip()
        url = entry["url"]
        if entry.get("link_pattern"):
            km = re.search(entry["link_pattern"], chunk, re.S | re.I)
            if not km:
                continue  # a heading with no job link is page furniture, not a posting
            url = requests.compat.urljoin(entry["url"], km.group(1))
        job = Job(title=title, company=entry["company"], location=location, url=url,
                  source="page", description="", work_mode=infer_work_mode(title, location, ""))
        jobs[job.job_id] = job
    return list(jobs.values())


def fetch_smartrecruiters(entry: dict, terms: list[str]) -> list[Job]:
    """SmartRecruiters public postings API (NBCUniversal). Config:
    {"provider": "smartrecruiters", "company": "NBCUniversal",
     "company_id": "NBCUniversal3"} (the id in the company's
    careers.smartrecruiters.com URL). One search per term, then the
    posting detail call for the description. Keyword search, so expiry
    is age-based."""
    base = f"https://api.smartrecruiters.com/v1/companies/{entry['company_id']}/postings"
    jobs: dict[str, Job] = {}
    for term in terms:
        resp = requests.get(base, params={"q": term, "limit": 100}, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        for p in resp.json().get("content", []):
            pid = p.get("id")
            if not pid or pid in jobs:
                continue
            loc = p.get("location") or {}
            location = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
            desc = ""
            try:
                det = requests.get(f"{base}/{pid}", headers=HEADERS, timeout=30)
                if det.status_code == 200:
                    sections = (det.json().get("jobAd") or {}).get("sections") or {}
                    desc = strip_html(" ".join(v.get("text", "") for v in sections.values() if isinstance(v, dict)))
            except requests.RequestException:
                pass
            title = p.get("name", "").strip()
            jobs[pid] = Job(
                title=title, company=entry["company"], location=location,
                url=f"https://jobs.smartrecruiters.com/{entry['company_id']}/{pid}",
                source="smartrecruiters", description=desc,
                date_posted=(p.get("releasedDate") or "")[:10], pay=extract_pay(desc),
                work_mode=_mode((loc.get("remote") and "remote") or "", title, location, desc),
            )
        time.sleep(1)
    return list(jobs.values())


BREEZY_DESC = re.compile(r'<div class="description[^"]*">(.*?)</div>\s*</div>', re.S)


def fetch_breezy(entry: dict, terms: list[str]) -> list[Job]:
    """Breezy HR (Bitdeer). `{slug}.breezy.hr/json` is the complete board
    with no descriptions, so each posting's page is fetched for its
    description div. Config: {"provider": "breezy", "company": "...",
    "slug": "bitdeer", "max_details": 60}. Full list, so expiry
    snapshot-diffs it.

    A board of 128 postings costs ~140 s to fetch in full, four times a
    day, so descriptions are fetched only for the `max_details` most
    recently published (default 60); older postings come back title-only
    and were already scored with their description when they were new.
    """
    resp = requests.get(f"https://{entry['slug']}.breezy.hr/json", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    items = sorted(resp.json(), key=lambda i: i.get("published_date") or "", reverse=True)
    budget = int(entry.get("max_details", 60))
    jobs = []
    for item in items:
        title = (item.get("name") or "").strip()
        url = item.get("url") or ""
        if not title or not url:
            continue
        loc = item.get("location") or {}
        location = loc.get("name") or ", ".join(
            x for x in (loc.get("city"), (loc.get("state") or {}).get("name"),
                        (loc.get("country") or {}).get("name")) if x)
        desc = ""
        if budget > 0:
            budget -= 1
            try:
                time.sleep(0.2)
                page = requests.get(url, headers=HEADERS, timeout=25)
                if page.status_code == 200:
                    m = BREEZY_DESC.search(page.text)
                    if m:
                        desc = strip_html(m.group(1))
            except requests.RequestException as e:
                log.debug("breezy detail fetch failed for %s: %s", url, e)
        remote = ((loc.get("remote_details") or {}).get("value") or "") if loc.get("is_remote") else ""
        jobs.append(Job(
            title=title, company=entry["company"], location=location, url=url,
            source="breezy", description=desc,
            date_posted=(item.get("published_date") or "")[:10],
            pay=(item.get("salary") or "").strip() or extract_pay(desc),
            work_mode=_mode(remote, title, location, desc),
        ))
    return jobs


PROVIDERS = {
    "radancy": fetch_radancy,
    "hibob": fetch_hibob,
    "adp": fetch_adp,
    "jibe": fetch_jibe,
    "page": fetch_page,
    "smartrecruiters": fetch_smartrecruiters,
    "breezy": fetch_breezy,
}


def fetch(config: dict) -> list[Job]:
    out: list[Job] = []
    for entry in config.get("career_sites", []):
        label = f"{entry['provider']}:{entry['company']}"
        try:
            got = PROVIDERS[entry["provider"]](entry, entry.get("terms") or config["search_terms"])
            out.extend(got)
            log.info("%s: %d postings", label, len(got))
            health.record(label, ok=True, count=len(got))
        except Exception as e:  # noqa: BLE001 - per-source isolation by design
            log.warning("SOURCE FAILURE %s: %s", label, e)
            health.record(label, ok=False, error=e)
        time.sleep(1)
    return out

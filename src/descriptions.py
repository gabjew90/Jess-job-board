"""Descriptions for tracked postings that the day's fetch did not return,
so a one-time re-score (config `rescore_scored_before`) reads the real
text. Older postings drop out of keyword searches, and without this they
keep a band scored under an outdated profile. Indeed answers in one
GraphQL batch; Workday answers per posting through its CxS job endpoint.
"""
import logging
import time

import requests

from . import expiry
from .util import HEADERS, strip_html

log = logging.getLogger(__name__)

SOURCES = ("indeed", "workday")
INDEED_QUERY = ("query Descriptions($keys: [ID!]!) { jobData(input: {jobKeys: $keys})"
                " { results { job { key expired description { html } } } } }")


def fetch(records: dict[str, dict]) -> dict[str, str]:
    """{job_id: plain-text description} for the records whose source can
    answer. A posting that is expired or cannot be fetched is left out."""
    out: dict[str, str] = {}
    keys = {jid: m.group(1) for jid, r in records.items()
            if r.get("source") == "indeed" and (m := expiry.INDEED_KEY.search(r.get("url", "")))}
    if keys:
        by_key = _indeed(sorted(set(keys.values())))
        out.update({jid: by_key[k] for jid, k in keys.items() if by_key.get(k)})
    for jid, r in records.items():
        if r.get("source") == "workday":
            time.sleep(0.3)
            text = _workday(r.get("url", ""))
            if text:
                out[jid] = text
    if records:
        log.info("Descriptions: fetched %d of %d for re-scoring", len(out), len(records))
    return out


def _indeed(keys: list[str]) -> dict[str, str]:
    headers = expiry.indeed_headers()
    if headers is None:
        return {}
    out: dict[str, str] = {}
    for i in range(0, len(keys), expiry.INDEED_BATCH):
        try:
            resp = requests.post(expiry.INDEED_API, headers=headers, timeout=60,
                                 json={"query": INDEED_QUERY,
                                       "variables": {"keys": keys[i:i + expiry.INDEED_BATCH]}})
            payload = resp.json()
            if resp.status_code != 200 or payload.get("errors"):
                log.warning("Indeed description fetch failed: %s", resp.status_code)
                return out
            for item in ((payload.get("data") or {}).get("jobData") or {}).get("results") or []:
                job = (item or {}).get("job") or {}
                html = (job.get("description") or {}).get("html")
                if job.get("key") and html and not job.get("expired"):
                    out[job["key"]] = strip_html(html)
        except Exception as e:  # noqa: BLE001
            log.warning("Indeed description fetch failed: %s", e)
            return out
    return out


def _workday(url: str) -> str:
    m = expiry.WORKDAY_URL.match(url)
    if not m:
        return ""
    tenant, wd, site, path = m.groups()
    try:
        resp = requests.get(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{path}",
                            headers={**HEADERS, "Accept": "application/json"}, timeout=20)
        if resp.status_code != 200:
            return ""
        return strip_html((resp.json().get("jobPostingInfo") or {}).get("jobDescription") or "")
    except Exception as e:  # noqa: BLE001
        log.debug("workday description fetch failed for %s: %s", url, e)
        return ""

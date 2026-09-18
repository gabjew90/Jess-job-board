"""jobspy source: Indeed, Glassdoor, ZipRecruiter, Google Jobs.

Each (site, term) pair is fetched independently so one blocked or broken
site never kills the run. Failures are logged loudly for the Actions log.
"""
import logging
import time

import pandas as pd
from jobspy import scrape_jobs

from .. import health
from ..models import Job
from ..util import extract_pay, infer_work_mode

log = logging.getLogger(__name__)

DEFAULT_RESULTS = 50


def _s(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value)


def _pay(row) -> str:
    lo, hi = row.get("min_amount"), row.get("max_amount")
    if lo and hi and not pd.isna(lo) and not pd.isna(hi):
        unit = {"yearly": "yr", "hourly": "hr", "monthly": "mo"}.get(
            _s(row.get("interval")), _s(row.get("interval")))
        return f"${lo:,.0f}–${hi:,.0f}" + (f"/{unit}" if unit else "")
    return extract_pay(_s(row.get("description")))


def _mode(row) -> str:
    if row.get("is_remote") is True:
        return "remote"
    return infer_work_mode(_s(row.get("title")), _s(row.get("location")),
                           _s(row.get("description")))


def fetch(config: dict) -> list[Job]:
    jobs: list[Job] = []
    # Company watch: employers without direct boards (Meta, Tesla...) get
    # burial-proof targeted queries — topic searches take a ranked slice per
    # term and Indeed's ranking routinely buries watched companies' roles.
    depth = config.get("results_per_term", DEFAULT_RESULTS)
    for company in config.get("indeed_company_watch", []):
        query = f'company:"{company}" (energy OR power OR "data center")'
        # Per-company health keys: jobspy returns an EMPTY FRAME (not an
        # exception) when Indeed blocks a request, so a shared key would
        # hide a mid-roster block behind the roster's total.
        label = f"indeed-watch:{company}"
        try:
            df = scrape_jobs(site_name=["indeed"], search_term=query,
                             location=config.get("location", "United States"),
                             results_wanted=depth,
                             hours_old=config.get("watch_hours_old", 168),
                             country_indeed="USA", verbose=0)
            for _, row in df.iterrows():
                jobs.append(Job(
                    title=_s(row.get("title")),
                    company=_s(row.get("company")),
                    location=_s(row.get("location")),
                    url=_s(row.get("job_url")),
                    source="indeed",
                    description=_s(row.get("description")),
                    date_posted=_s(row.get("date_posted")),
                    pay=_pay(row),
                    work_mode=_mode(row),
                ))
            log.info("jobspy company-watch %r: %d results", company, len(df))
            health.record(label, ok=True, count=len(df))
        except Exception as e:  # noqa: BLE001 - per-source isolation by design
            log.warning("SOURCE FAILURE company-watch %r: %s", company, e)
            health.record(label, ok=False, error=e)
        time.sleep(1)

    for term in config["search_terms"]:
        for site in config["sites"]:
            try:
                df = scrape_jobs(
                    site_name=[site],
                    search_term=term,
                    # Google Jobs needs a natural-language query with locale
                    # and freshness to return results.
                    google_search_term=f"{term} jobs in the United States since last week",
                    location=config.get("location", "United States"),
                    results_wanted=depth,
                    hours_old=config.get("hours_old", 72),
                    country_indeed="USA",
                    verbose=0,
                )
                for _, row in df.iterrows():
                    jobs.append(Job(
                        title=_s(row.get("title")),
                        company=_s(row.get("company")),
                        location=_s(row.get("location")),
                        url=_s(row.get("job_url")),
                        source=_s(row.get("site")) or site,
                        description=_s(row.get("description")),
                        date_posted=_s(row.get("date_posted")),
                        pay=_pay(row),
                        work_mode=_mode(row),
                    ))
                log.info("jobspy %s / %r: %d results", site, term, len(df))
                health.record(f"jobspy:{site}", ok=True, count=len(df))
            except Exception as e:  # noqa: BLE001 - per-source isolation by design
                log.warning("SOURCE FAILURE jobspy %s / %r: %s", site, term, e)
                health.record(f"jobspy:{site}", ok=False, error=e)
            time.sleep(1)
    return jobs

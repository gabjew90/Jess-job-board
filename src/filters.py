"""Relevance filter, title exclusions, and priority-topic flagging.

Two-tier relevance: generic keywords (energy, power, grid, ...) only count
when they appear in the TITLE — job descriptions are full of boilerplate
("high-energy team", "workplace flexibility") that made description-wide
matching keep nearly everything. Description matches require specific
domain phrases ("battery energy storage", "grid interconnection", ...).
"""
import re

from .models import Job


def is_relevant(job: Job, config: dict) -> bool:
    title = job.title.lower()
    if any(k.lower() in title for k in config["title_keywords"]):
        return True
    description = job.description.lower()
    if any(k.lower() in description for k in config["description_keywords"]):
        return True
    # Rescue rule: curated-company postings whose titles lack energy words
    # (e.g. "Senior Director, Development" at a datacenter developer) — needs
    # BOTH a senior/role-type title signal AND an energy phrase in the
    # description, so company boilerplate alone can't drag in recruiters.
    return (any(k.lower() in title for k in config.get("rescue_title_keywords", []))
            and any(k.lower() in description
                    for k in config.get("rescue_description_keywords", [])))


# Leadership titles are never excluded — "Director, Field Services" must
# survive the "field service" trade-role exclusion.
EXCLUSION_OVERRIDES = ("director", "head of", "vice president", "principal",
                       "chief", "product manager", "program manager",
                       "senior manager")


def is_excluded(job: Job, exclusions: list[str]) -> bool:
    title = job.title.lower()
    if any(o in title for o in EXCLUSION_OVERRIDES):
        return False
    # Word boundaries so "mechanic" can't match "Mechanical", etc.
    return any(re.search(rf"\b{re.escape(e.lower())}\b", title)
               for e in exclusions)


def is_priority(job: Job, topics: list[str]) -> bool:
    text = f"{job.title} {job.description}".lower()
    return any(t.lower() in text for t in topics)


def apply_filters(jobs: list[Job], config: dict) -> list[Job]:
    # Mission-pure companies (keep_all boards): every posting is on-topic by
    # virtue of the employer; triage sorts fit instead of the keyword filter.
    keep_all_companies = {
        e["company"]
        for key in ("ats_boards", "workday_boards", "successfactors_boards",
                    "career_sites")
        for e in config.get(key, []) if e.get("keep_all")}
    kept = []
    for job in jobs:
        if is_excluded(job, config["title_exclusions"]):
            continue
        if job.company not in keep_all_companies and not is_relevant(job, config):
            continue
        job.priority = is_priority(job, config["priority_topics"])
        kept.append(job)
    return kept

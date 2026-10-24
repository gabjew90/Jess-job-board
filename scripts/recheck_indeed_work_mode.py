"""One-off: recompute the work mode of open Indeed records with the
tightened rules (2026-10-23). jobspy's is_remote is a bare keyword match,
so "remote diagnostics" and the like made on-site roles read remote. Indeed
postings stop being re-fetched once they age out of the search window, so
the backlog is read here: Indeed's job API returns each posting's tags
("Remote", "Hybrid work", "In-person") and description.

The description decides, through util.infer_work_mode (arrangement phrasing
only). A tag fills in when the description says nothing, since tags can
contradict the text ("In-person" on a posting "open to remote candidates
anywhere within the United States"); such a mode is stored as
work_mode_by "tag", which a later fetch keeps unless it finds a mode
itself. Modes the scorer read are left alone: work_mode_by "triage", or,
on a record from before that field, a mode the old bare-word rules don't
explain (util.legacy_text_mode). Run from the repo root; commit
state/seen_jobs.json after.

    python -m scripts.recheck_indeed_work_mode [--dry-run]
"""
import logging
import sys
import time
from collections import Counter

import requests

from src import expiry, state as state_mod
from src.util import infer_work_mode, legacy_text_mode

log = logging.getLogger("work-mode")
QUERY = ("query J($keys: [ID!]!) { jobData(input: {jobKeys: $keys}) { results { job {"
         " key title location { formatted { long } } attributes { label }"
         " description { text } } } } }")
BATCH = 50


def tag_mode(labels: list[str]) -> str:
    low = {label.strip().lower() for label in labels}
    if any(label.startswith("hybrid") for label in low):
        return "hybrid"
    if any(label == "remote" or label.startswith("remote ") or label == "work from home"
           for label in low):
        return "remote"
    if low & {"in-person", "in person", "on-site", "onsite"}:
        return "onsite"
    return ""


def fetch(keys: list[str]) -> dict[str, dict]:
    api_headers = expiry.indeed_headers()
    if api_headers is None:
        raise SystemExit("jobspy's Indeed app headers not found")
    out = {}
    for i in range(0, len(keys), BATCH):
        resp = requests.post(expiry.INDEED_API, json={"query": QUERY,
                             "variables": {"keys": keys[i:i + BATCH]}},
                             headers=api_headers, timeout=60)
        resp.raise_for_status()
        data = (resp.json().get("data") or {}).get("jobData") or {}
        for result in data.get("results") or []:
            job = (result or {}).get("job")
            if job and job.get("key"):
                out[job["key"]] = job
        time.sleep(0.5)
    return out


def main(dry_run: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seen = state_mod.load()
    recs = {}
    for rec in seen.values():
        m = expiry.INDEED_KEY.search(rec.get("url", ""))
        if (m and rec.get("source") == "indeed" and rec.get("active", True)
                and rec.get("work_mode_by") != "triage"):
            recs.setdefault(m.group(1), []).append(rec)
    jobs = fetch(sorted(recs))
    moves = Counter()
    for key, job in jobs.items():
        labels = [(a or {}).get("label") or "" for a in job.get("attributes") or []]
        location = ((job.get("location") or {}).get("formatted") or {}).get("long") or ""
        desc = (job.get("description") or {}).get("text") or ""
        text = infer_work_mode(job.get("title") or "", location, desc)
        tag = "" if text else tag_mode(labels)
        mode, by = (text, "fetch") if text else (tag, "tag" if tag else "")
        for rec in recs[key]:
            old = rec.get("work_mode", "")
            if rec.get("work_mode_by") is None and old and not legacy_text_mode(old, desc):
                moves[("kept as scorer's", old)] += 1
                if not dry_run:
                    rec["work_mode_by"] = "triage"
                continue
            if old != mode:
                moves[(old or "-", mode or "-")] += 1
                if not dry_run:
                    rec.update(work_mode=mode, work_mode_by=by)
    log.info("%d open Indeed records, %d answered: changes %s", len(recs), len(jobs),
             dict(moves.most_common()))
    if not dry_run and moves:
        state_mod.save(seen)


if __name__ == "__main__":
    main("--dry-run" in sys.argv)

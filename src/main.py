"""Daily pipeline: scrape → filter → dedupe → persist → dashboard → notify."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (dashboard, discovery, expiry, feedback, filters,
               health, notify, screen, state as state_mod, triage)
from .models import Job
from .util import company_key
from .sources import (ats_boards, career_sites, hyperscalers, jobspy_source,
                      successfactors, workday)

log = logging.getLogger(__name__)

LATEST_RUN = Path("data/latest_run.json")
DESCRIPTION_CAP = 2000  # chars kept per job for the triage step


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = json.loads(Path("config.json").read_text())

    raw = (jobspy_source.fetch(config) + hyperscalers.fetch(config)
           + ats_boards.fetch(config) + workday.fetch(config)
           + successfactors.fetch(config) + career_sites.fetch(config))
    log.info("Fetched %d raw postings", len(raw))
    health.save_run()
    for s in health.summary():
        if s["status"] != "ok":
            log.warning("SOURCE HEALTH %s: %s (last results: %s)",
                        s["source"], s["status"], s["last_results"] or "never")

    kept = filters.apply_filters(raw, config)
    log.info("%d postings after relevance filter/exclusions", len(kept))

    seen = state_mod.load()
    # Title screen: model judgment on postings not yet tracked — rescues
    # flat titles at target employers past the keyword gate and drops the
    # obvious misfits it let through. Rejects feed the weekly filter audit.
    kept, rejected, screen_stats = screen.apply(raw, kept, seen, config)

    fb = feedback.load()
    kept = [j for j in kept if not feedback.matches(j, fb["hide"])]

    feedback.sweep_state(seen, fb["hide"])
    archive_floor = config.get("auto_archive_below", 25)
    feedback.apply_verdicts(seen, fb["verdicts"], archive_floor)
    closed_recs = expiry.sweep(seen, raw, config)
    new_jobs = state_mod.split_new(kept, seen)
    seen = state_mod.prune(seen, config.get("state_retention_days", 180))
    log.info("%d NEW postings (%d tracked total)", len(new_jobs), len(seen))

    # Full records (with capped descriptions), for inspection/debugging.
    LATEST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LATEST_RUN.write_text(json.dumps(
        [{**j.to_dict(), "description": j.description[:DESCRIPTION_CAP]} for j in new_jobs],
        indent=1,
    ) + "\n")

    # Rescue records left unscored by previously failed triage chunks:
    # they'd otherwise never be scored again (score() only sees new jobs).
    new_ids = {j.job_id for j in new_jobs}
    desc_by_id = {j.job_id: j.description for j in raw if j.description}
    # A record merged from another source's copy is keyed by that copy's
    # id, so the description this run fetched is also found by company and
    # the exact title (not group_key, whose 40-character title prefix lets
    # two different postings share a description).
    exact = lambda company, title: (company_key(company), " ".join(title.lower().split()))
    desc_by_title = {exact(j.company, j.title): j.description for j in raw if j.description}

    def description_for(jid: str) -> str:
        r = seen[jid]
        return desc_by_id.get(jid) or desc_by_title.get(
            exact(r.get("company", ""), r.get("title", "")), "")

    # A record's key is the job_id it was stored under; a title renamed in
    # place no longer hashes to it, so rebuilt jobs map back explicitly.
    state_key: dict[str, str] = {}

    def from_record(jid: str) -> Job:
        r = seen[jid]
        job = Job(title=r["title"], company=r["company"], location=r["location"],
                  url=r["url"], source=r["source"], description=description_for(jid))
        state_key[job.job_id] = jid
        return job

    rescue_jobs = [from_record(jid) for jid in state_mod.unscored_active(seen, new_ids)]
    if rescue_jobs:
        log.warning("Rescuing %d previously unscored records (failed chunks)",
                    len(rescue_jobs))

    # One-time re-scoring after a rubric or fetcher change: records scored
    # before `rescore_scored_before` are scored again when they banded strong
    # or top, or come from a source in `rescore_sources` (any band, archived
    # low scores included: a source that fed the scorer bad descriptions
    # mis-banded low as well as high). Only when this run fetched the
    # posting's description, so the new band reads the real text; at most
    # `rescore_max_per_run` per run; owner verdicts are never overwritten.
    # Remove the keys when done.
    rescore_jobs = []
    cutoff = config.get("rescore_scored_before")
    if cutoff:
        taken = new_ids | {j.job_id for j in rescue_jobs}
        sources = set(config.get("rescore_sources", []))

        def wanted(r: dict) -> bool:
            if r.get("hidden") or r.get("excluded") or r.get("duplicate"):
                return False
            if r.get("source") in sources:
                return r.get("active", True) or r.get("lowscore")
            return r.get("active", True) and r.get("band") in ("top", "strong")

        due = [jid for jid, r in seen.items()
               if jid not in taken and wanted(r)
               and not (r.get("scoring_fingerprint") or {}).get("owner")
               and (r.get("scoring_fingerprint") or {}).get("at", "") < cutoff
               and description_for(jid)]
        due.sort(key=lambda jid: (seen[jid].get("band") != "top",
                                  seen[jid].get("band") != "strong"))
        rescore_jobs = [from_record(jid) for jid in due[:config.get("rescore_max_per_run", 60)]]
        if rescore_jobs:
            log.info("Re-scoring %d of %d records scored before %s",
                     len(rescore_jobs), len(due), cutoff)

    to_score = new_jobs + rescue_jobs + rescore_jobs
    scores = triage.score(to_score, fb["text"])
    fingerprint = triage.scoring_fingerprint(fb["text"])
    # Clear misfits (score < 25) are auto-archived: they stay in state for
    # dedupe but never occupy the dashboard or future attention.
    for job in to_score:
        s = scores.get(job.job_id)
        if not s:
            continue
        rec = seen.get(state_key.get(job.job_id, job.job_id))
        owner = rec is not None and (rec.get("scoring_fingerprint") or {}).get("owner")
        if rec is not None and not owner:  # an owner's verdict is never overwritten
            rec.update({k: s[k] for k in ("band", "score", "rationale",
                                          "seniority_match")})
            rec["scoring_fingerprint"] = fingerprint
            if s["score"] < archive_floor:
                rec["active"] = False
                rec["closed"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                rec["lowscore"] = True
            elif rec.get("lowscore"):
                # Re-scored above the floor: an archived low score comes back.
                rec.update(active=True, lowscore=False)
                rec.pop("closed", None)
        # LLM-extracted pay/mode fill gaps only — structured API fields win.
        for field in ("pay", "work_mode"):
            if s.get(field) and not getattr(job, field):
                setattr(job, field, s[field])
                if rec is not None and not rec.get(field):
                    rec[field] = s[field]
    # Band distribution per run — a static distribution while the input mix
    # moves means the model is regressing to the band center.
    from collections import Counter
    dist = Counter(s["band"] for s in scores.values())
    log.info("Band distribution this run: %s", dict(dist))
    dist_file = Path("state/band_distribution.json")
    hist = json.loads(dist_file.read_text()) if dist_file.exists() else []
    hist.append({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                 "scored": len(scores), "bands": dict(dist)})
    dist_file.write_text(json.dumps(hist[-120:], indent=1) + "\n")

    state_mod.save(seen)

    # Learn coverage: companies repeatedly surfacing strong/top roles that we
    # only see via aggregators get their direct board found and wired in, so
    # future postings arrive with canonical links, descriptions and exact
    # expiry instead of an aggregator copy that dies on its own schedule.
    discovered, unresolved = discovery.run(seen, config)
    if discovered:
        cfg_path = Path("config.json")
        cfg = json.loads(cfg_path.read_text())
        for d in discovered:
            cfg.setdefault(d["kind"], []).append(d["entry"])
        # A wired company no longer needs its Indeed watch query.
        cfg["indeed_company_watch"] = [
            c for c in cfg.get("indeed_company_watch", [])
            if not any(discovery.same_org(c, d["company"]) for d in discovered)]
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
        config = cfg
        for d in discovered:
            log.info("Wired direct board: %s via %s/%s",
                     d["company"], d["provider"], d["board"])

    dashboard.generate(seen, health.summary(),
                       config.get("dashboard_max_rows", 500))

    # Digest covers a rolling window rather than only this run's finds:
    # several runs fire per day, so a run-scoped digest could strand
    # postings between two notifications. Overlap is intentional.
    window_h = config.get("digest_window_hours", 24)
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=window_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    window = [r for r in seen.values()
              if r.get("active", True)
              and (r["first_seen_at"] >= cutoff if r.get("first_seen_at")
                   else r.get("first_seen") == today)]

    if new_jobs or closed_recs:
        # Digest floor never sits below the archive floor.
        digest_floor = max(config.get("digest_min_score", 40), archive_floor)
        # Weekly (Mondays): sample archived records for hand-grading — the
        # archive filter's false-negative rate is invisible otherwise.
        audit_recs, reject_audit = [], []
        if datetime.now(timezone.utc).weekday() == 0:
            import random
            archived = [r for r in seen.values()
                        if r.get("lowscore") or (not r.get("active", True)
                                                 and (r.get("score") or 99) < 25)]
            audit_recs = random.sample(archived, min(10, len(archived)))
            # The filter's false negatives are otherwise invisible: nothing
            # it rejects reaches state. Sample this run's rejects too.
            reject_audit = [j.to_dict() for j in
                            random.sample(rejected, min(10, len(rejected)))]
        log.info("Digest: %d postings in the last %dh (%d new this run)",
                 len(window), window_h, len(new_jobs))
        notify.post_issue(window, health.summary(), closed_recs,
                          digest_floor, unresolved, audit_recs, discovered,
                          reject_audit, screen_stats)
    else:
        log.info("No new or closed postings; skipping notification.")


if __name__ == "__main__":
    main()

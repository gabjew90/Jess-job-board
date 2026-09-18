"""Daily pipeline: scrape → filter → dedupe → persist → dashboard → notify."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (dashboard, discovery, expiry, feedback, filters,
               health, notify, screen, state as state_mod, triage)
from .models import Job
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
    rescue_jobs = [
        Job(title=seen[jid]["title"], company=seen[jid]["company"],
            location=seen[jid]["location"], url=seen[jid]["url"],
            source=seen[jid]["source"], description=desc_by_id.get(jid, ""))
        for jid in state_mod.unscored_active(seen, new_ids)
    ]
    if rescue_jobs:
        log.warning("Rescuing %d previously unscored records (failed chunks)",
                    len(rescue_jobs))

    to_score = new_jobs + rescue_jobs
    scores = triage.score(to_score, fb["text"])
    fingerprint = triage.scoring_fingerprint(fb["text"])
    # Clear misfits (score < 25) are auto-archived: they stay in state for
    # dedupe but never occupy the dashboard or future attention.
    archive_floor = config.get("auto_archive_below", 25)
    for job in to_score:
        s = scores.get(job.job_id)
        if not s:
            continue
        rec = seen.get(job.job_id)
        if rec is not None:
            rec.update({k: s[k] for k in ("band", "score", "rationale",
                                          "seniority_match")})
            rec["scoring_fingerprint"] = fingerprint
            if s["score"] < archive_floor:
                rec["active"] = False
                rec["closed"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                rec["lowscore"] = True
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
    discovered = discovery.run(seen, config)
    if discovered:
        cfg_path = Path("config.json")
        cfg = json.loads(cfg_path.read_text())
        cfg["ats_boards"].extend(discovered)
        watch_out = {d["company"].lower() for d in discovered}
        cfg["indeed_company_watch"] = [c for c in cfg.get("indeed_company_watch", [])
                                       if c.lower() not in watch_out]
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
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
        suggestions = notify.coverage_suggestions(seen, config)
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
                          digest_floor, suggestions, audit_recs, discovered,
                          reject_audit, screen_stats)
    else:
        log.info("No new or closed postings; skipping notification.")


if __name__ == "__main__":
    main()

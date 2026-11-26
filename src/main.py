"""Daily pipeline: scrape → filter → dedupe → persist → dashboard → notify."""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (dashboard, descriptions, discovery, expiry, feedback, filters,
               health, notify, screen, state as state_mod, triage)
from .models import Job
from .util import company_key
from .sources import (ats_boards, career_sites, hyperscalers, jobspy_source,
                      successfactors, workday)

log = logging.getLogger(__name__)

LATEST_RUN = Path("data/latest_run.json")
DESCRIPTION_CAP = 2000  # chars kept per job for the triage step


# Hours that must pass before another digest goes out (owner, 2026-11-22:
# one a day). Two runs on the same day sit 1-3 hours apart; consecutive
# days' runs, 18 or more.
DIGEST_GAP_HOURS = 12

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

    fb = feedback.load(config.get("feedback_authors", []))
    kept = [j for j in kept if not feedback.matches(j, fb["hide"])]

    feedback.sweep_state(seen, fb["hide"])
    archive_floor = config.get("auto_archive_below", 25)
    feedback.apply_verdicts(seen, fb["verdicts"], archive_floor)
    feedback.apply_log(seen)
    closed_recs = expiry.sweep(seen, raw, config)
    new_jobs = state_mod.split_new(kept, seen)
    seen = state_mod.prune(seen, config.get("state_retention_days", 180))
    successfactors.backfill_pay(seen, config.get("pay_backfill_per_run", 40))
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

    backfill: dict[str, str] = {}   # fetched for re-scoring (see below)

    def description_for(jid: str) -> str:
        r = seen[jid]
        return backfill.get(jid) or desc_by_id.get(jid) or desc_by_title.get(
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
    # before `rescore_scored_before` are scored again when they banded in
    # `rescore_bands` (default top and strong), or come from a source in
    # `rescore_sources` (any band, archived
    # low scores included: a source that fed the scorer bad descriptions
    # mis-banded low as well as high). Only when this run fetched the
    # posting's description, or the posting's own source returns it now
    # (descriptions.fetch), so the new band reads the real text; at most
    # `rescore_max_per_run` per run; owner verdicts are never overwritten.
    # Remove the keys when done.
    rescore_jobs = []
    cutoff = config.get("rescore_scored_before")
    if cutoff:
        taken = new_ids | {j.job_id for j in rescue_jobs}
        sources = set(config.get("rescore_sources", []))
        bands = set(config.get("rescore_bands", ["top", "strong"]))
        unknown = bands - set(triage.BAND_ORDER)
        if unknown:
            log.warning("rescore_bands has unknown band(s) %s; they match nothing", sorted(unknown))

        def wanted(r: dict) -> bool:
            if state_mod.suppressed(r) or r.get("applied"):
                return False
            if r.get("source") in sources:
                return r.get("active", True) or r.get("lowscore")
            return r.get("active", True) and r.get("band") in bands

        due = [jid for jid, r in seen.items()
               if jid not in taken and wanted(r)
               and not (r.get("scoring_fingerprint") or {}).get("owner")
               and ((r.get("scoring_fingerprint") or {}).get("at") or "") < cutoff
               and (description_for(jid) or r.get("source") in descriptions.SOURCES)]
        rank = {b: i for i, b in enumerate(reversed(triage.BAND_ORDER))}   # top first
        due.sort(key=lambda jid: rank.get(seen[jid].get("band"), len(rank)))
        total, cap = len(due), config.get("rescore_max_per_run", 60)
        # Fetch in slices until the cap is filled, so postings whose page
        # cannot be read do not take the slots on every run.
        picked, pos = [], 0
        while len(picked) < cap and pos < min(len(due), 3 * cap):
            batch = due[pos:pos + cap - len(picked)]
            pos += len(batch)
            backfill.update(descriptions.fetch({jid: seen[jid] for jid in batch
                                                if not description_for(jid)}))
            picked += [jid for jid in batch if description_for(jid)]
        rescore_jobs = [from_record(jid) for jid in picked]
        if rescore_jobs:
            log.info("Re-scoring %d of %d records scored before %s",
                     len(rescore_jobs), total, cutoff)

    to_score = new_jobs + rescue_jobs + rescore_jobs
    scores = triage.score(to_score, fb["text"])
    # A re-score that drops a top, strong or possible record two or more
    # bands is checked once more (triage.confirm_drops).
    triage.confirm_drops(rescore_jobs, scores,
                         {j.job_id: seen[state_key[j.job_id]] for j in rescore_jobs}, fb["text"])
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
            rec.pop("pay_capped", None)
            rec["scoring_fingerprint"] = fingerprint
            if s["score"] < archive_floor:
                rec["active"] = False
                rec["closed"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                rec["lowscore"] = True
            elif rec.get("lowscore") and not state_mod.suppressed(rec):
                # Re-scored above the floor: an archived low score comes back.
                rec.update(active=True, lowscore=False)
                rec.pop("closed", None)
        # LLM-extracted pay/mode fill gaps only — structured API fields win.
        for field in ("pay", "work_mode"):
            if s.get(field) and not getattr(job, field):
                setattr(job, field, s[field])
                if rec is not None and not rec.get(field):
                    rec[field] = s[field]
                    if field == "work_mode":
                        rec["work_mode_by"] = "triage"
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

    floor = config.get("pay_floor", 0)
    capped = sum(triage.pay_cap(r, floor) for r in seen.values()
                 if r.get("active", True) or r.get("pay_capped"))
    if capped:
        log.info("Pay floor $%s: %d records capped at possible", f"{floor:,.0f}", capped)
    # Best matches (owner, 2026-11-26): top roles whose title matches config
    # "spotlight" sort first on the board and lead the digest.
    try:
        spot = re.compile(config.get("spotlight") or "(?!)", re.I)
    except re.error as e:
        log.warning("config spotlight is not a valid pattern (%s); no best matches", e)
        spot = re.compile("(?!)")
    for r in seen.values():
        # Applied roles have their own section and no pin.
        if (r.get("active", True) and r.get("band") == "top" and not r.get("applied")
                and spot.search(r.get("title") or "")):
            r["spotlight"] = True
        else:
            r.pop("spotlight", None)
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
                       config.get("dashboard_max_rows", 500),
                       theme=config.get("theme"),
                       title=config.get("board_title", "Job Watcher"))

    # One digest a day (owner, 2026-11-22): runs fire more than once a day,
    # and a rolling 24h window sent the same roles twice. A later run the
    # same day posts nothing; what it found waits for the next digest,
    # which covers everything since the one before. Applied roles never
    # appear. Closures likewise accumulate until a digest reports them.
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    last = state_mod.last_digest()
    window_h = config.get("digest_window_hours", 24)
    since = last or (now - timedelta(hours=window_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # A posting that went out unrated (its scoring chunk failed) comes back
    # once rated, though it was first seen before this window.
    window = [r for r in seen.values()
              if r.get("active", True) and not r.get("applied")
              and ((r["first_seen_at"] > since if r.get("first_seen_at")
                    else r.get("first_seen") == today)
                   or (r.get("digest_unrated") and r.get("band")))]
    closed_since = (since[:10] if last else today)
    # Reported per closure date, so a posting that reopens and closes again
    # is reported again.
    closed_list = [r for r in seen.values()
                   if not r.get("active", True)
                   and r.get("closed_notified") != str(r.get("closed", ""))[:10]
                   and not (r.get("lowscore") or (state_mod.suppressed(r) and not r.get("owner_closed")))
                   and str(r.get("closed", ""))[:10] >= closed_since]
    since_dt = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    hours = max(1, round((now - since_dt).total_seconds() / 3600))

    # Elapsed time, not the calendar day: a digest posted just after UTC
    # midnight (a hand-run in the owner's evening) must not cost the next
    # morning's. The owner's runs on one day sit a few hours apart.
    if last and hours < DIGEST_GAP_HOURS:
        log.info("Last digest %dh ago (%s); %d postings and %d closures wait "
                 "for the next one", hours, last, len(window), len(closed_list))
    elif window or closed_list:
        # Digest floor never sits below the archive floor.
        digest_floor = max(config.get("digest_min_score", 40), archive_floor)
        # Weekly (Mondays): sample archived records for hand-grading — the
        # archive filter's false-negative rate is invisible otherwise.
        audit_recs, reject_audit = [], []
        if now.weekday() == 0:
            import random
            archived = [r for r in seen.values()
                        if r.get("lowscore") or (not r.get("active", True)
                                                 and r.get("score") is not None
                                                 and r["score"] < 25)]
            audit_recs = random.sample(archived, min(10, len(archived)))
            # The filter's false negatives are otherwise invisible: nothing
            # it rejects reaches state. Sample this run's rejects too.
            reject_audit = [j.to_dict() for j in
                            random.sample(rejected, min(10, len(rejected)))]
        log.info("Digest: %d postings and %d closures since %s (%d new this run)",
                 len(window), len(closed_list), since, len(new_jobs))
        if notify.post_issue(window, health.summary(), closed_list,
                             digest_floor, unresolved, audit_recs, discovered,
                             reject_audit, screen_stats, theme=config.get("theme"),
                             window_hours=hours):
            for r in closed_list:
                r["closed_notified"] = str(r.get("closed", ""))[:10]
            for r in window:
                if r.get("band"):
                    r.pop("digest_unrated", None)
                else:
                    r["digest_unrated"] = True
            state_mod.save(seen)
            state_mod.mark_digest(now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    else:
        log.info("No new or closed postings since the last digest; skipping notification.")


if __name__ == "__main__":
    main()

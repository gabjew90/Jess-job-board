"""One-off: re-probe postings the retired 30-day timer closed and reopen the
ones their source still lists. Run from the repo root after pulling the
latest state; commit state/seen_jobs.json afterwards.

    python -m scripts.reopen_timer_closures [--dry-run]

Only records closed by the timer are considered: inactive, not hidden by
feedback, not auto-archived as a low score, and from a source the sweep
never snapshot-diffed or probed at the time (anything outside the ATS
providers, Microsoft and Google). A record reopens only on a definitive
"alive" from its probe; unknowns stay closed.
"""
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from src import expiry, state as state_mod

log = logging.getLogger("reopen")
STATE = Path("state/seen_jobs.json")
TIMER_SOURCES = set(expiry.PROBES) - {"microsoft", "google-careers"} | {"indeed"}


def main(dry_run: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seen = json.loads(STATE.read_text())
    candidates = {jid: r for jid, r in seen.items()
                  if not r.get("active", True) and not r.get("hidden")
                  and not r.get("lowscore") and r.get("source") in TIMER_SOURCES}
    log.info("%d timer-closed candidates: %s", len(candidates),
             dict(Counter(r["source"] for r in candidates.values())))

    alive: set[str] = set()
    indeed = {jid: expiry.INDEED_KEY.search(r.get("url", "")) for jid, r in candidates.items()
              if r["source"] == "indeed"}
    indeed = {jid: m.group(1) for jid, m in indeed.items() if m}
    if indeed:
        verdict = expiry._indeed_expired(sorted(set(indeed.values()))) or {}
        alive |= {jid for jid, key in indeed.items() if verdict.get(key) is False}
    for jid, rec in candidates.items():
        probe = expiry.PROBES.get(rec["source"])
        if probe is None:
            continue
        time.sleep(0.3)
        if probe(rec) is True:
            alive.add(jid)

    log.info("%d still open: %s", len(alive),
             dict(Counter(candidates[j]["source"] for j in alive)))
    log.info("by band: %s", dict(Counter(candidates[j].get("band") for j in alive)))
    if dry_run:
        return
    for jid in alive:
        seen[jid]["active"] = True
        seen[jid].pop("closed", None)
    state_mod.save(seen)
    log.info("reopened %d records in %s", len(alive), STATE)


if __name__ == "__main__":
    main("--dry-run" in sys.argv)

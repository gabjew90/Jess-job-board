"""One-off: close the SuccessFactors postings that were removed but still
answer 200 with the site's job-details shell (PG&E and NextEra, found
2026-10-02). The old probe only knew the /errorpage/ redirect, so they
stayed open, and with about half of this board's SuccessFactors postings
dead at once the sweep's mass-closure guard would hold the backlog back.
This runs the new probe (shell page AND gone from the site's own search)
over every open SuccessFactors posting, without that guard. Run from the
repo root after pulling the latest state; commit state/seen_jobs.json
afterwards.

    python -m scripts.close_successfactors_shells [--dry-run]
"""
import logging
import sys
import time

from src import expiry, state as state_mod

log = logging.getLogger("sf-shells")


def main(dry_run: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seen = state_mod.load()
    recs = [r for r in seen.values()
            if r.get("active", True) and r.get("source") == "successfactors"]
    verdicts = {True: 0, False: 0, None: 0}
    for rec in recs:
        time.sleep(0.3)
        alive = expiry._successfactors_alive(rec.get("url", ""), rec.get("title", ""))
        verdicts[alive] += 1
        if alive is False:
            log.info("Closing: %s @ %s", rec.get("title"), rec.get("company"))
            if not dry_run:
                expiry._close(rec)
        elif alive is None:
            log.info("Left open (unknown): %s @ %s", rec.get("title"), rec.get("company"))
    log.info("%d checked: %d closed, %d open, %d unknown (left open)",
             len(recs), verdicts[False], verdicts[True], verdicts[None])
    if not dry_run and verdicts[False]:
        state_mod.save(seen)


if __name__ == "__main__":
    main("--dry-run" in sys.argv)

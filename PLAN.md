# Job Watcher — Architecture Plan

Agreed 2026-08-13 after brainstorm. Deviations from the original reference
prompt (ScottCoffin/Job_Scraper reproduction) are intentional and noted.

> **Inherited document.** This is the design and decisions log of the
> upstream watcher (gabjew90/Job-watcher) this repo was forked from. The
> pipeline decisions still hold and are why the code looks the way it does.
> Two things do NOT apply here: the resume drafter, which is removed from
> this repo, and the targeting (goal, domains, scoring thesis), which is
> set by this repo's own `profile.md` and `config.json`.

## Goal

Daily monitor for manager-to-director roles in power project development
and origination, on-site and behind-the-meter generation, and data center
power. Discovery and scoring only. No LinkedIn scraping, no auto-applying.

## Pipeline

```
sources (jobspy | hyperscaler APIs | ATS boards)
  → normalize to a common Job record
  → keyword relevance filter + title exclusions + priority-topic flagging
  → dedupe against state/seen_jobs.json
  → new jobs: GitHub Issue digest + docs/ dashboard (GitHub Pages)
  → Claude triage (score 0-100, rationale, seniority check)
  → resume drafts on demand (dashboard ✍️ → issue), from experience_library.md only
```

## Decisions log

| Decision | Choice | Why |
|---|---|---|
| Scraping | jobspy + hyperscaler JSON endpoints + **ATS board APIs** (Greenhouse/Lever/Ashby) | Glassdoor/ZipRecruiter often block Actions IPs; ATS APIs are stable JSON and precisely target the ecosystem companies |
| State | JSON (`state/seen_jobs.json`), not SQLite | Diffable, mergeable, no binary blobs in git; pruned at 180 days |
| Notifications | **GitHub Issue digest** (not Discord) | Zero extra secrets, GitHub app push + email built in, browsable archive |
| Dashboard | Static HTML in `docs/`, served by GitHub Pages | Real URL, regenerated each run |
| LLM | **Headless Claude Code on Max subscription OAuth token** (`CLAUDE_CODE_OAUTH_TOKEN` secret), not the pay-per-token API | Zero incremental cost; mint with `claude setup-token` |
| Workflows | One daily workflow (scrape → triage → draft → commit → notify) | Two workflows adds coordination for no benefit at this scale |
| Cost control | Skip LLM step entirely when zero new postings; batch all new postings in one prompt | |
| Scoring model (2026-09) | **Sonnet** for banding (was Haiku); Haiku for the new title screen | 71% of keyword-filter passes were banded weak/misfit and 70% failed seniority — the calibration rules are judgment calls; volume is ~50 postings/run so the stronger model is cheap. Eval gates the switch |
| Title screen (2026-09) | Haiku pass over NEW postings' title+company before the keyword gate is final: rescues flat titles at target employers, drops obvious misfits; drops remembered 60 days and binding on later runs; scope outranks function in the prompt (a VP of facilities owns a strategy, an assistant building engineer does the work); `eval/screen_cases.json` grades it over three passes on a keep-rate floor plus a hard fail for any case missed in every pass, since an all-must-hold gate on a 97%-accurate sampled classifier would be red half the time on luck; Monday digest samples the rejects | Keyword filter was recall-first with unmeasured false negatives; a judged pre-pass both raises recall and cuts the junk the full scorer paid for |
| Scoring policy in one place (2026-09) | `triage.finalize()` applies the code-side band policy (the seniority cap) inside `triage.score()`, so production and the eval get the same final band; `scoring_fingerprint` hashes the prompt and policy version alongside the rubric | The cap lived in `main.py`, so the eval graded an intermediate band no record ever carried, and editing the prompt or the cap left the fingerprint unchanged while the meaning of a band moved |
| Board identity (2026-09) | Discovery accepts a guessed board only on stated identity (Greenhouse returns the organization's name) or, where the provider states none, two distinct known titles matching with one exact and one non-generic; name comparison is whole-name, not `company_key` | Title resemblance is not identity — thousands of companies post a "Senior Product Manager" — and `company_key`, built to merge cross-source twins, calls "Hive Systems" and "HIVE Digital" the same company, which is the exact confusion discovery exists to avoid |
| Draft delivery after push (2026-09) | The pipeline queues the issue comment in `state/pending_delivery.json`; the workflow posts and closes via `python -m src.deliver` only after the commit is pushed, and the GitHub write helpers report HTTP failure | Commenting and closing inside the pipeline announced files the workflow had not yet committed, so a failed push closed a request pointing at links nobody could open |
| Resume drafts (2026-09) | On-demand only (dashboard ✍️ → issue). The model returns structured JSON words; code owns a one-page DOCX layout (python-docx), the PDF is that DOCX via LibreOffice, and the page count is verified. `resume_style.md` (owner-curated) sets the voice and its ✔ rules are linted in code; a fabrication guard drops any unit whose numbers, dates or employers are not in the library; ATS keyword coverage with one library-bounded revision pass; gaps go to the issue comment | Free-form Markdown drafts varied in layout, carried inline TODOs and read as AI prose (308 em-dashes in 25 drafts); code-owned format plus a deterministic guard make the file sendable and invented facts checkable |
| JS-rendered careers sites (2026-09) | Fetch the vendor JSON endpoint behind the page (Radancy/HiBob/ADP/Jibe in `career_sites.py`); a headless browser is a **discovery tool only** (`scripts/probe_careers_site.js`), never part of the daily run | Every such site is fed by a plain JSON call; capturing it once is cheaper and more robust than rendering in CI, and full-list feeds get exact expiry like ATS boards |
| Posting liveness (2026-09) | A posting closes only when its source says it is gone: full-list sources are snapshot-diffed, keyword-search sources are probed per posting (Indeed `jobData(jobKeys)` in batches of 500, Workday CxS 404, SuccessFactors error-page redirect, Amazon and SmartRecruiters 404, Jibe req_id search, Microsoft and Google as before); a probe that reports most of a source dead in one run closes nothing; no timer | The 30-day age-out had closed 472 Indeed postings of which two thirds were still open, while a fifth of the active ones had expired; every source turned out to expose an exact per-posting check |

## Phases

- **Phase 1 — DONE**: config, jobspy source, filter/dedupe/state, GitHub Issue
  digest, Pages dashboard, daily Actions workflow. Live-validated; filters
  tightened to two-tier (title keywords vs. description phrases) after the
  first real run showed description-boilerplate noise.
- **Phase 2 — DONE**: hyperscaler direct fetchers (Microsoft via Eightfold
  pcsx API, Amazon search.json, Google careers embedded JSON; Meta written
  but disabled — blocks datacenter IPs) + ATS board fetchers
  (Greenhouse/Lever/Ashby) for the curated company list in config.
- **Phase 3 — DONE**: Claude triage (`src/triage.py`, headless `claude -p`,
  Haiku scoring / Sonnet drafting) + `profile.md` + `experience_library.md`
  template + resume drafting to `drafts/`, wired into the daily workflow.
  Live-validated: 162/166 postings scored in 5 batched calls; drafting
  correctly held off while the library is a template. (Superseded 2026-09:
  Sonnet scoring; drafting is on-demand, see the decisions log.)

## Hard rules

- Resume drafts draw ONLY from `experience_library.md`; never invent metrics,
  skills, employers, or accomplishments. Insufficient library → reported as
  gaps on the draft-request issue; the resume omits it. A deterministic
  guard drops any line whose numbers, dates or employers are not in the
  library, and any skills term with a word the library never uses.
- Per-source try/except: one broken endpoint never kills the run; failures
  logged visibly in Actions output.
- No secrets in code. `CLAUDE_CODE_OAUTH_TOKEN` as repo secret; the issue
  digest uses the workflow's own `GITHUB_TOKEN`.

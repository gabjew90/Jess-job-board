# Setting up your own job watcher

This repo scrapes job boards daily, has a model judge each posting against
*your* background, and posts a ranked digest as a GitHub issue plus a
dashboard page. It was built for one person; this document turns it into
yours.

**How to use this:** create an empty GitHub repo, open it in Claude Code,
and paste this whole file in as your first message. Claude will work
through it, interviewing you where it needs your judgment. Expect about an
hour, most of it answering questions about your career.

**What you need before starting**

1. Your resume, as a file (PDF or Word both fine), in the repo folder.
2. A GitHub repo you own, empty.
3. The `CLAUDE_CODE_OAUTH_TOKEN` from the person who shared this repo —
   the same token and the same Claude account the original watcher uses.
   You do not need your own subscription. See "Sharing one Claude
   account" at the end for what that implies.
4. Nothing else. No servers, no API keys, no paid services. GitHub Actions
   runs it free.

---

## Instructions for Claude Code

Work through these steps in order. Steps 3 and 4 need the owner's input —
stop and ask, don't guess. Everything else you can do alone.

### Step 1 — Clone the source, drop the resume drafter

```bash
git clone https://github.com/gabjew90/Job-watcher.git /tmp/source
rsync -a --exclude .git /tmp/source/ .     # or: cp -r /tmp/source/. . && rm -rf .git-source
```

Copy everything, then remove what you don't want — an allowlist of paths
drifts as the repo changes, and `config.json` in particular is needed in
step 4. `profile.md` and `feedback.md` come across as templates and get
replaced below.

This setup covers the job board and digest only, not the resume drafter.
Remove it:

- Delete `src/resume.py`, `src/draft_requests.py`, `src/deliver.py`,
  `tests/test_resume.py`, `resume_style.md`, `experience_library.md`,
  `experience_library_archive.md`, `drafts/`.
- In `src/main.py`: drop the `draft_requests` import, the
  `drafts = draft_requests.process(...)` call, `drafts` from the
  `if new_jobs or closed_recs or drafts:` gate and from
  `notify.post_issue(...)`. Pass an empty list where a `drafts` argument
  is required.
- In `src/dashboard.py`: remove the ✍️ draft-request button and the
  `draft_url` / `draft_body` block that builds it.
- In `.github/workflows/daily.yml`: remove the "Install LibreOffice
  Writer" step and the "Deliver queued draft announcements" step.
- In `.github/workflows/tests.yml`: remove the `src/resume.py`,
  `src/draft_requests.py` and `resume_style.md` path filters and the
  `python-docx` install.

Run `python -m pytest -q tests` and fix anything that still imports the
removed modules. Tests must pass before you continue.

### Step 2 — Wipe the previous owner's data

This is the step that matters most. Skipping it means the new owner
inherits 5,000 postings judged against someone else's career.

- `state/seen_jobs.json`, `state/screened_out.json`,
  `state/discovery_attempts.json` → `{}`
- `state/band_distribution.json`, `state/source_health.json` → the empty
  shape their loaders expect (check each loader; usually `[]` or
  `{"runs": []}`)
- `data/latest_run.json` → `[]`
- `docs/index.html` → delete; the first run regenerates it
- `feedback.md` → empty it, but keep any header comment explaining the
  format. Calibration is personal and must start blank.
- `eval/cases.json` and `eval/screen_cases.json` → `{"cases": []}`.
  Both evals treat an empty file as nothing to check, so CI stays green
  until real cases accumulate.

### Step 3 — Build `profile.md` from the owner's resume

**Read their resume first**, then interview them. `profile.md` is the only
thing the scorer knows about them, so this step determines the quality of
everything downstream. Do not write it from the resume alone — a resume
says what someone *did*, and this file has to say what they *want next*,
which is not the same and is often the opposite.

First **summarise what you took from the resume** — current role and
scope, level, domain, the through-line of their career — and ask them to
correct it. That covers everything a resume already states, and their
corrections are usually more revealing than the resume was.

Then ask only these five. Each one is something a resume structurally
cannot answer, because a resume is retrospective and this file is about
what they want next. Ask one or two at a time, conversationally, and push
back when an answer is vague: "senior roles in tech" is not usable,
"director-level product management at a climate hardware company" is.

1. **What next** — the titles they want, the function, and whether this
   is a step up or a move sideways. (Their current level is on the
   resume; the direction of travel is not, and the scorer caps any
   posting it reads as a seniority mismatch, so this has teeth.)
2. **Domain** — which industries or subject areas, and whether that is
   the same field they are in now or a deliberate change. If they name
   more than three, ask which they would take over the others.
3. **The near miss** — a posting that looks right on paper but they would
   turn down, and why: the function, the level, the industry, the company
   stage. This is the highest-yield question in the list. The positive
   case is largely inferable from the resume plus question 1; the
   boundary is not, and a digest full of plausible near misses is the
   most common way this tool becomes annoying.
4. **Never** — role types to reject outright. Common ones: quota-carrying
   sales, on-call operations, people-management when they want IC, IC
   when they want management, consulting, pre-sales, relocation.
5. **Hard constraints** — location, remote / hybrid / onsite,
   compensation floor, work authorization, travel tolerance, company size
   or stage. None of this is on a resume and all of it decides whether a
   posting is worth their attention.

Target employers are worth a passing question but do not need their own
round: the config step below covers companies, and the discovery module
finds them from results anyway.

Then write `profile.md` following the structure of the original
(fetch `/tmp/source/profile.md` and mirror its shape, not its content):

```
# Candidate profile (used by the triage scorer)
  Two or three paragraphs: who they are, what they own now, what they
  are moving toward. Written as evidence, not aspiration.
## Score HIGH (75-100, seniority permitting)
  The core thesis. What makes a posting a top match.
## Secondary sweet spot (70-90)
  Adjacent matches worth surfacing.
## Score LOW
  What to push down, with the reason. Their "never" list lives here.
## Seniority calibration
  How to read titles for this person.
```

Show them the draft and revise it with them before moving on. This file
is theirs — they should recognise themselves in it.

### Step 4 — Retarget `config.json`

Keep the file's structure; replace the targeting. With the owner:

- `search_terms` — 5 to 8 phrases they'd type into a job site. These
  drive the Indeed search and are the main source on day one.
- `title_keywords`, `description_keywords` — domain words that mark a
  posting as relevant.
- `rescue_title_keywords` — seniority and function words ("director",
  "principal", "head of", "product manager") that let a flat title at a
  good company survive the keyword filter.
- `title_exclusions` — words that disqualify outright ("intern",
  "technician", whatever their "never" list implies).
- `priority_topics` — the subset that earns a ⭐ in the digest.
- `location`, `hours_old`, `watch_hours_old` — usually fine as-is.

**Companies: keep the broad employers, drop the specialists.** Most of the
inherited list is specific to power and data-centre infrastructure and is
wrong for anyone else. But three groups hire across almost every function
— product, finance, operations, legal, marketing, research — so they are
worth keeping whatever the field:

- **Hyperscalers** (`hyperscalers`): Microsoft, Amazon, Google, Meta.
  Leave enabled.
- **Developers and operators** of large projects and sites: Vantage Data
  Centers, Equinix, Brookfield, Crusoe, Aligned, QTS, Switch, Compass.
- **Funds and investors**: Blackstone, Brookfield, KKR, Stonepeak,
  Generate Capital, DigitalBridge, Energy Capital Partners.

Delete the rest — the equipment makers, the battery and grid specialists,
the utilities — unless the new owner's field actually touches them.

**One cost caveat when choosing how to keep them.** Sources come in two
kinds, and it decides how much screening the first weeks cost:

- *Keyword-searched* (`workday_boards`, `successfactors_boards`,
  `hyperscalers`, `indeed_company_watch`, and the jibe/smartrecruiters
  career sites) return only postings matching the search terms — a few
  dozen each. Cheap. Keep these freely.
- *Full-list* (`ats_boards` on greenhouse/lever/ashby, and the
  radancy/hibob/adp/breezy career sites) return the employer's ENTIRE
  board — SpaceX returns 2,463 postings, OpenAI 816, Anthropic 603. Every
  one of those is a candidate for the title screen, which judges at most
  600 per run, so a handful of large boards means weeks of working
  through a backlog before the pipeline reaches a steady state.

So prefer the Workday/Indeed entry for a big diversified employer over its
Greenhouse board, and keep full-list boards for employers whose whole
board is plausibly relevant. A tight `title_exclusions` list also helps:
excluded titles are dropped before the screen ever sees them.

Beyond that, do not rebuild a hundred companies by hand. The discovery
module watches for companies that repeatedly surface strong roles and
wires their boards in automatically over the first couple of weeks, which
is how the original list grew. Seed a handful the owner names and let it
accumulate.

### Step 5 — Retarget the title screen

`src/screen.py` holds a prompt with a hardcoded list of domains — the only
place in the code that names the previous owner's field. In STEP 1 and
STEP 2 of that prompt, replace the domain list with theirs, and replace
the three worked examples with equivalents from their field. Keep the
structure exactly: it is an ordered procedure, and its reliability comes
from that ordering.

The scorer (`src/triage.py`) needs no edit — it reads `profile.md`.

### Step 6 — Wire up GitHub

1. Repo → Settings → Secrets and variables → Actions → add
   `CLAUDE_CODE_OAUTH_TOKEN`, with the same value as the original repo's.
   This is the one step that must be done in the GitHub UI.
2. Repo → Settings → Pages → Source: Deploy from a branch → your default
   branch, `/docs`. This publishes the dashboard.
3. In `.github/workflows/daily.yml`, set the schedule: **one slot a day,
   at a different hour from the other watcher's.** The original runs at
   13:37 and 16:37 UTC, so `- cron: "37 19 * * *"` (12:37 Pacific) keeps
   them apart. Staggering matters because both draw on one Claude
   account: overlapping runs compete for the same limit, and when
   something does go wrong it is obvious which run spent what.
4. Commit and push everything.

### Step 7 — First run

Trigger "Daily job watch" manually from the Actions tab. It takes 15–25
minutes. Then check:

- A new issue titled "Job watch <date>: N postings in 24h" exists.
- Its table has bands (top / strong / possible / weak) and rationales
  that make sense to the owner. If everything is "misfit", `profile.md`
  or the search terms are wrong — fix and re-run before doing anything
  else.
- The dashboard is live at `https://<user>.github.io/<repo>/`.
- The Actions log shows postings fetched, screened and scored, with no
  `SCREEN FAILURE` or `TRIAGE FAILURE` lines.

### Step 8 — Tell the owner how it learns

The first week will be mediocre; it gets good because they correct it.

- Every digest row has a feedback link. When a band is wrong, they click
  it and say why in plain language. That note goes into `feedback.md` and
  steers every future run.
- When a correction represents a *rule* rather than a one-off, add a case
  to `eval/cases.json` so the rule can't silently regress.
- The Monday digest samples ten postings the filter rejected. Reading
  that sample is the only way to find out what the filter is quietly
  losing.

---

## Notes

**Sharing one Claude account.** Both watchers run on the same
subscription and the same token. That is fine, and the pipelines are not
what puts it at risk: a run costs about five cheap screening calls plus
two to eight scoring calls, so both watchers together are roughly fifteen
model calls a day.

What does exhaust the weekly limit is long interactive Claude sessions on
that account — the original's limit was hit on 2026-09-15 during heavy
interactive work, not by the cron. The pipeline then ran for two days
scoring nothing, silently, because every call returned 429 and the
pipeline is built to degrade rather than crash.

So: **know the symptom**, which is a digest whose table has no bands, and
`You've hit your weekly limit · resets <time>` in the Actions log. If you
see it, nothing is broken — wait for the reset and trigger a run
manually. The next run rescores everything it missed automatically, so
nothing is lost but time.

A new owner's first weeks cost more than a steady state, because the
title screen works through a backlog at 600 titles per run. Keeping large
full-list boards out of the starting config (see step 4) is what keeps
that backlog short.

**Cost.** GitHub Actions is free at this volume. The model calls are the
only cost: roughly five cheap screening calls plus two to eight scoring
calls per run, which is minutes of Haiku and Sonnet time.

**What will need attention later.** Job boards change their APIs without
notice. `state/source_health.json` tracks every source's last successful
fetch, and the digest surfaces sources that have gone quiet — that is the
signal to look, and fixing a fetcher is usually a small change to one
file in `src/sources/`.

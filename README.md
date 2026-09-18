# Job Watcher

Daily monitor for manager-to-director roles in **power project development
and origination, on-site and behind-the-meter generation, and data center
power** — developers and IPPs, infrastructure funds, data center operators,
and industrial operators building their own generation.

Scrapes job boards daily via GitHub Actions, filters and dedupes, scores
each new posting for fit with Claude, posts a GitHub Issue digest, and
renders a dashboard on GitHub Pages.

## How it works

```
jobspy (Indeed/Glassdoor/ZipRecruiter/Google Jobs)
hyperscaler APIs (Microsoft/Amazon/Google/Meta careers)
ATS boards (Greenhouse/Lever/Ashby — curated ecosystem companies)
Workday / SuccessFactors boards (Brookfield, Blackstone, Vantage, Equinix,
  GE Vernova, Bloom Energy, NiSource, AltaGas, SOLV, PG&E, NextEra)
careers-site APIs (Radancy/HiBob/ADP/Jibe/SmartRecruiters/Breezy —
  Applied Digital)
  → keyword filter + title exclusions + priority-topic ⭐
  → title screen: Haiku judges new postings' title+company, dropping obvious
    misfits and rescuing keyword-rejected titles that carry a leadership or
    role-type signal (rescue_title_keywords); ≤600 titles/run (screen.py)
  → dedupe vs state/seen_jobs.json  (committed each run)
  → Claude triage: fit band vs profile.md + feedback (Sonnet, batched)
  → GitHub Issue digest (sorted by score) + docs/index.html dashboard
```

- **Schedule**: once daily at 19:37 UTC / 12:37 Pacific
  (`.github/workflows/daily.yml`), plus manual runs via the Actions tab
  (`workflow_dispatch`). One slot a day, staggered away from the other
  watcher that shares this Claude subscription.
- **Notifications**: each run with new postings opens a GitHub Issue labeled
  `job-digest`. Watch the repo (or install the GitHub mobile app) to get
  push/email notifications. No extra secrets needed.
- **State**: `state/seen_jobs.json`, pruned after 180 days, so only
  never-before-seen postings surface.

## Setup

1. **Enable GitHub Pages**: repo Settings → Pages → deploy from branch,
   folder `/docs`. The dashboard then lives at
   `https://gabjew90.github.io/Jess-job-board/`.
2. **Add the triage secret**: run `claude setup-token` on your own machine
   (requires a Claude subscription), then save the token as a repo secret
   named `CLAUDE_CODE_OAUTH_TOKEN` (Settings → Secrets and variables →
   Actions). No API key billing — triage runs on your subscription. Without
   the secret, runs still work; digests are just unscored.
3. **Tune `config.json`**: search terms, keyword filter, title exclusions,
   priority topics, ATS boards, retention. `profile.md`
   is what postings are scored against — keep it current.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

Without `GITHUB_TOKEN` set, the digest is printed to stdout instead of
posted. `data/latest_run.json` holds the current run's new postings with
descriptions (input for the triage step).

## Adding / fixing sources

**Coverage doctrine**: every company worth watching either has a direct
board entry (`ats_boards` / `workday_boards` / `successfactors_boards` /
`career_sites`) OR belongs in `indeed_company_watch`, which runs a targeted
`company:"X" (energy OR power OR "data center")` Indeed query per company
each run — topic searches cap at 25 ranked results and routinely bury
individual employers' postings. The digest's 🔭 coverage-suggestions
section surfaces new candidates automatically.

**ATS boards** (most reliable source — stable public JSON): add an entry to
`ats_boards` in `config.json`. Find a company's board slug from its careers
page URL, or probe:

```
https://boards-api.greenhouse.io/v1/boards/<slug>/jobs
https://api.lever.co/v0/postings/<slug>?mode=json
https://api.ashbyhq.com/posting-api/job-board/<slug>
```

**JavaScript-rendered careers sites** (`career_sites` in `config.json`):
employers whose careers pages carry no postings in their HTML — plain
`requests` sees an empty shell, and they used to reach the digest only via
Indeed. Every such page is fed by a JSON endpoint; `src/sources/career_sites.py`
fetches four vendor platforms directly (Radancy, HiBob, ADP WorkforceNow,
Jibe/iCIMS). No browser runs in the pipeline. To wire a new employer, find
its endpoint with a headless browser's network capture:

```bash
npm i -g playwright && npx playwright install chromium
NODE_PATH="$(npm root -g)" node scripts/probe_careers_site.js https://careers.example.com/jobs
```

(`NODE_PATH` because Node never resolves `require()` from the global
`node_modules` on its own; a local `npm i playwright` works without it.)

It prints the page's job links and every API-shaped response (URL, status,
first bytes). The call carrying the postings names the platform: a
`jobsapi-google.m-cloud.io` search is Radancy (config `tenant` = the uuid in
its `companyName` parameter), `*.careers.hibob.com/api/job-ad` is HiBob
(`slug` = subdomain), `workforcenow.adp.com/.../job-requisitions` is ADP
(`cid`/`ccId` from the page URL), `/api/jobs?keywords=` is Jibe (`base` =
the careers host), `api.smartrecruiters.com/v1/companies/<id>/postings`
is SmartRecruiters (`company_id` = that id), `{slug}.breezy.hr/json` is
Breezy (`slug` = the subdomain; descriptions come from each posting
page). A page that lists its openings as plain HTML with no
ATS at all (Flux Power's HubSpot page) uses the `page` provider: a
`title_pattern` regex whose group 1 is the title, plus optional
`location_pattern` and `link_pattern` searched in the HTML after each
title; a title with no link is skipped. A platform not in the module
needs a new fetcher there, same shape as the others. Not every site yields: Tesla sits behind Akamai
and denies datacenter IPs even to a real browser.

**Fixing a broken hyperscaler fetcher** (they use undocumented endpoints
that move when sites redesign): open the career site's search page in a
browser, DevTools → Network tab → filter XHR/Fetch, run a search, and find
the request returning job JSON. Copy its URL and params into the matching
fetcher at the top of `src/sources/hyperscalers.py`. Verified endpoints as
of 2026-08 are noted there — e.g. Microsoft moved from
`gcsservices.careers.microsoft.com` to the Eightfold-powered
`apply.careers.microsoft.com/api/pcsx/search` in 2026.

## Notes

- Glassdoor/ZipRecruiter block datacenter IPs (Cloudflare) — expect
  `SOURCE FAILURE` warnings for them on most runs; each (site, search-term)
  pair is isolated so the rest of the run is unaffected. Meta similarly
  rejects non-residential traffic, so its fetcher ships disabled
  (`hyperscalers.meta` in config).
- Microsoft search results carry no descriptions, so each Microsoft job's
  full description is fetched from the per-job API (cached per run).
- Amazon pay ranges are NOT capturable: amazon.jobs renders them via a
  JavaScript widget from an internal API — they appear in no fetchable
  text (search API, page HTML, or per-job JSON). Amazon rows show blank
  pay by design; check the posting page.
- Posting liveness: a posting closes only when its source says it is gone,
  never on a timer. Full-list sources (ATS boards; Radancy/HiBob/ADP/Breezy
  careers sites; the Edged feed) are snapshot-diffed exactly; keyword-search
  sources are probed each run (Indeed by job key through its API, Workday
  through the CxS job endpoint, SuccessFactors by its error-page redirect,
  Amazon and SmartRecruiters by 404, Jibe by req_id search, Microsoft and
  Google as before). A probe that reports most of a source dead in one run
  is treated as broken and closes nothing.
- Filter recall is audited, not assumed: every Monday the digest samples
  ten postings the title screen (or, without the CLI, the keyword filter)
  turned away before scoring, alongside ten auto-archived ones. Rejects
  never reach state, so that sample is the only view of what the filter
  loses. Screen drops are remembered in `state/screened_out.json` (60
  days) so a title is judged once, and a remembered drop binds on every
  later run — until 2026-09-18 it did not, and 962 of 5,178 tracked
  records were postings the screen had already turned away.
- Board discovery proves identity before wiring a company's board into
  `config.json`: Greenhouse states the organization's own name and a
  mismatch rejects the board however well its titles line up; Ashby and
  Lever state none, so there two distinct known titles must match, one
  exactly, at least one carrying a non-generic word. (The name check is
  deliberately not `util.company_key`, which collapses a name to its first
  word — under it "Hive Systems" and "HIVE Digital" are the same company.)
- Both model gates have regression evals (`python -m src.eval_runner`,
  CI on any change to the prompts, rubric or feedback). Scoring
  (`eval/cases.json`) grades the band production stores, since
  `triage.score` applies the code-side policy. The title screen
  (`eval/screen_cases.json`) is graded asymmetrically: keeping a posting
  that should drop costs one scoring call (WARN), dropping one that
  should keep loses the role outright, because the screen decides without
  a description and remembers its answer. It is also a sampled
  classifier: at 97% per-judgement accuracy, demanding a clean sweep of
  27 judgements would fail 44% of runs on luck alone, so the run fails
  instead on a case dropped in EVERY pass (reproducible, so real) or on
  the keep rate falling below 23/27. A case kept in some passes but not
  all prints as UNSTABLE — a prompt smell, not a build break.
- No LinkedIn scraping. No auto-applying. Discovery and scoring only.

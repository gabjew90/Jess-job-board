"""Claude triage: score new postings for fit.

Runs headless Claude Code (`claude -p`), authenticated in CI via the
CLAUDE_CODE_OAUTH_TOKEN repo secret (minted with `claude setup-token`) —
subscription usage, no API key. Scoring uses Sonnet — the calibration
rules in feedback.md (seniority from described scope, not title) are
judgment calls a stronger model gets right more often, and the volume
(~50 postings a run, batched) keeps it cheap. The title screen
(screen.py) uses Haiku.

Cost hygiene: the whole step is skipped when there are no new postings and
scoring is batched (CHUNK jobs per call).
"""
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from .models import Job
from .util import role_excerpt

log = logging.getLogger(__name__)

PROFILE = Path("profile.md")
CHUNK = 40
# Pinned model versions (CLI aliases like "haiku" drift across releases);
# override via env for experiments.
SCORE_MODEL = os.environ.get("JOBWATCH_SCORE_MODEL", "claude-sonnet-5")

# Bands make the four real decisions (archive / hide / show / rank)
# explicit instead of manufacturing 0-100 precision nobody uses. The
# mapped scores keep config thresholds (archive <25, digest floor 40,
# coverage >=70) working unchanged.
BAND_SCORE = {"top": 90, "strong": 75, "possible": 55, "weak": 35, "misfit": 15}
BAND_ORDER = ["misfit", "weak", "possible", "strong", "top"]

SCORE_PROMPT = """You are a job-fit triage assistant. Classify each posting below into ONE
fit band for this candidate:

{profile}
{feedback}

Bands (apply the profile's guidance; where it gives numeric ranges they map
as: 85+ = top, 70-84 = strong, 55-69 = possible, 40-54 = weak, <40 = misfit):
- top: unambiguous target role — a "Score HIGH" category at the right seniority
- strong: solid fit — HIGH category with minor gaps, or a stated secondary sweet spot
- possible: plausible fit with real gaps (adjacent domain, uncertain seniority or scope)
- weak: marginal relevance to the candidate's targets
- misfit: out of scope

Return ONLY a JSON array, no prose, one object per posting:
{{"job_id": "...", "band": "top|strong|possible|weak|misfit",
  "rationale": "one sentence", "seniority_match": true/false,
  "pay": "...", "work_mode": "..."}}

seniority_match = false when the role is below (or far above) the
candidate's director/senior-PM level, e.g. technician, junior, or pure IC
engineering roles.

pay = the salary/compensation range exactly as stated in the posting text,
compact (e.g. "$153,000–$180,000/yr"); "" if the posting doesn't state pay.
work_mode = "onsite", "hybrid", or "remote" ONLY if the posting says so or
it is unambiguous; "" otherwise. Never guess either field.

Postings:
{postings}"""

def available() -> bool:
    return shutil.which("claude") is not None


def _run_claude(prompt: str, model: str) -> str:
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json"],
        input=prompt, capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0:
        hint = ("" if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
                else " (CLAUDE_CODE_OAUTH_TOKEN is not set — add it as a repo "
                     "secret, see README)")
        raise RuntimeError(
            f"claude exited {result.returncode}{hint}: "
            f"{(result.stderr or result.stdout)[-500:]}")
    payload = json.loads(result.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude error result: {str(payload.get('result'))[:500]}")
    return payload["result"]


def _parse_json(text: str):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in response: {text[:200]}")
    return json.loads(text[start:end + 1])


# The code-side scoring policy. The model answers a band; the band that
# ships is this function applied to that answer. It lives here, not in
# main.py, so the eval grades what production serves — while the cap was
# in main.py the eval graded an intermediate band no record ever carried.
# Bump POLICY_VERSION when this policy changes, so scoring_fingerprint
# distinguishes records scored under it.
SENIORITY_CAP = "weak"
POLICY_VERSION = 1


def finalize(result: dict, title: str = "") -> dict:
    """Apply the code-side policy to one model result, in place.

    Seniority coupling is enforced here rather than in the prompt: a
    posting the model marked a seniority mismatch cannot band above weak,
    whatever fit it otherwise shows.
    """
    if (not result.get("seniority_match")
            and BAND_ORDER.index(result["band"]) > BAND_ORDER.index(SENIORITY_CAP)):
        log.info("Seniority cap: %r %s -> %s", title[:45], result["band"],
                 SENIORITY_CAP)
        result["band"] = SENIORITY_CAP
        result["score"] = BAND_SCORE[SENIORITY_CAP]
    return result


def score(new_jobs: list[Job], feedback_text: str = "") -> dict[str, dict]:
    """Return {job_id: {score, rationale, seniority_match, pay, work_mode}}."""
    if not new_jobs:
        return {}
    if not available():
        log.warning("claude CLI not found; skipping triage.")
        return {}
    log.info("Scoring with model %s", SCORE_MODEL)
    profile = PROFILE.read_text()
    feedback = (f"\nThe candidate has given feedback on past results — honor it "
                f"and generalize from the reasons given:\n{feedback_text}\n"
                if feedback_text.strip() else "")
    results: dict[str, dict] = {}
    for i in range(0, len(new_jobs), CHUNK):
        chunk = new_jobs[i:i + CHUNK]
        try:
            results.update(_score_chunk(chunk, profile, feedback))
            # A model occasionally omits an item from the array. One retry
            # on just the omissions, instead of leaving them for next run's
            # rescue pass (and failing the eval outright).
            missing = [j for j in chunk if j.job_id not in results]
            if missing and len(missing) < len(chunk):
                log.info("Retrying %d posting(s) omitted from the response", len(missing))
                results.update(_score_chunk(missing, profile, feedback))
            log.info("Triage chunk %d-%d scored (%d results)",
                     i + 1, i + len(chunk), len(results))
        except Exception as e:  # noqa: BLE001 - a failed chunk shouldn't kill the run
            log.warning("TRIAGE FAILURE on chunk %d-%d: %s", i + 1, i + len(chunk), e)
    titles = {j.job_id: j.title for j in new_jobs}
    for job_id, result in results.items():
        finalize(result, titles.get(job_id, ""))
    return results


def _score_chunk(chunk: list[Job], profile: str, feedback: str) -> dict[str, dict]:
    postings = "\n\n".join(
        f"job_id: {j.job_id}\ntitle: {j.title}\ncompany: {j.company}\n"
        f"location: {j.location}\ndescription: {role_excerpt(j.description, 1500)}"
        for j in chunk
    )
    raw = _run_claude(SCORE_PROMPT.format(profile=profile, feedback=feedback,
                                          postings=postings), SCORE_MODEL)
    out: dict[str, dict] = {}
    for item in _parse_json(raw):
        band = str(item.get("band", "")).lower().strip()
        if band not in BAND_SCORE:
            log.warning("Invalid band %r for %s — left unscored",
                        band, item.get("job_id"))
            continue  # unscored records get rescued next run
        mode = str(item.get("work_mode", "")).lower()
        out[str(item["job_id"])] = {
            "band": band,
            "score": BAND_SCORE[band],
            "rationale": str(item.get("rationale", "")),
            "seniority_match": bool(item.get("seniority_match", False)),
            "pay": str(item.get("pay", "") or ""),
            "work_mode": mode if mode in ("onsite", "hybrid", "remote") else "",
        }
    return out


def scoring_fingerprint(feedback_text: str) -> dict:
    """Provenance stamped on every scored record: which model, when, a hash
    of the fully resolved rubric (profile.md + feedback file + open feedback
    issues), and a hash of the code-side regime (prompt, band scale, policy).
    Two records with different fingerprints were scored under different
    regimes and are not directly comparable. The rubric hash alone was not
    enough: editing the prompt or the seniority cap changed what a band
    meant while leaving the fingerprint identical."""
    import hashlib
    from datetime import datetime, timezone
    rubric = PROFILE.read_text() + "\n" + feedback_text
    policy = "\n".join([SCORE_PROMPT, str(POLICY_VERSION), SENIORITY_CAP,
                        json.dumps(BAND_SCORE, sort_keys=True)])
    return {
        "model": SCORE_MODEL,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "rubric": hashlib.sha1(rubric.encode()).hexdigest()[:10],
        "policy": hashlib.sha1(policy.encode()).hexdigest()[:10],
    }

"""Automatic direct-board discovery for companies that keep producing good roles.

Aggregator copies expire independently, carry no descriptions, and bury
postings. So when a company repeatedly surfaces strong/top-band roles but
we only see it through Indeed, this module tries to find its ATS board and
wires it into config.json.

VERIFICATION IS MANDATORY. Slug guessing is treacherous — "galaxy" is a
security installer, not Galaxy Digital; "hive" is a SaaS vendor, not HIVE
Digital. A wrong guess must fail the check and be discarded, so a bad slug
costs nothing but a request.

Identity, not resemblance, decides. Where the provider states whose board
it is, that statement settles it: Greenhouse's board endpoint returns the
organization's own name, so the name is compared and a mismatch rejects
the board however well its titles line up. Ashby and Lever publish no
organization name, so there the evidence is titles, and one match is not
enough: "Senior Product Manager" is posted by thousands of unrelated
companies. Two distinct known titles must match, one of them exactly, and
at least one must carry a token that is not generic recruiting vocabulary.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .util import HEADERS, company_key, title_key

log = logging.getLogger(__name__)

ATTEMPTS_FILE = Path("state/discovery_attempts.json")
RETRY_DAYS = 30
# Each probe is ~12 cheap requests; attempts are recorded so a company
# is retried only after RETRY_DAYS. A backlog works itself off in days.
MAX_PER_RUN = 8
STRONG_SCORE = 75

PROBES = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                   lambda d: [j.get("title", "") for j in d.get("jobs") or []]),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json",
              lambda d: [j.get("text", "") for j in d or []]),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}",
              lambda d: [j.get("title", "") for j in d.get("jobs") or []]),
}
# Providers that state whose board it is. Only Greenhouse does; Ashby and
# Lever return postings with no organization name anywhere in the payload.
NAME_API = {"greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}"}
# Recruiting vocabulary that identifies no company. A title made only of
# these words is evidence of nothing.
GENERIC = {"senior", "sr", "junior", "jr", "staff", "principal", "lead",
           "head", "chief", "vice", "president", "vp", "director", "manager",
           "management", "associate", "assistant", "specialist", "analyst",
           "engineer", "engineering", "product", "project", "program",
           "operations", "development", "developer", "strategy", "strategic",
           "business", "technical", "global", "regional", "the", "and", "for"}
MIN_TITLE_MATCHES = 2  # where the provider names no organization


def slug_variants(company: str) -> list[str]:
    base = re.sub(r"[^a-z0-9 ]", "", company.lower())
    base = re.sub(r"\b(inc|llc|corp|corporation|company|ltd|co|holdings|group)\b",
                  "", base).strip()
    words = base.split()
    if not words:
        return []
    joined = "".join(words)
    out = [joined, "-".join(words), words[0]]
    if len(words) > 1:
        out.append("".join(words[:2]))
    # drop single generic words that would collide with unrelated boards
    return [s for s in dict.fromkeys(out)
            if len(s) > 3 and s not in {"energy", "power", "data", "grid", "clean"}]


def _tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", title.lower()))


def _distinctive(title: str) -> bool:
    """True when the title says something about the employer, not just about
    seniority and function."""
    return bool(_tokens(title) - GENERIC)


def title_evidence(board_titles: list[str], known: list[str]) -> tuple[int, bool, bool]:
    """(distinct known titles matched, any matched exactly, any distinctive).

    Token overlap absorbs Sr./Senior-style differences, and is measured
    against the LONGER title so that a generic board title cannot be a
    subset-match for a longer known one ("Product Manager" scoring 1.0
    against "Senior Product Manager, Grid").
    """
    known_keys = {title_key(t): t for t in known}
    matched: set[str] = set()
    exact = distinctive = False
    for bt in board_titles:
        hit = known_keys.get(title_key(bt))
        if hit is not None:
            matched.add(hit)
            exact = True
            distinctive = distinctive or _distinctive(hit)
            continue
        bt_tokens = _tokens(bt)
        for kt in known:
            k_tokens = _tokens(kt)
            if not (k_tokens and bt_tokens):
                continue
            if len(k_tokens & bt_tokens) / max(len(k_tokens), len(bt_tokens)) >= 0.7:
                matched.add(kt)
                distinctive = distinctive or _distinctive(kt)
    return len(matched), exact, distinctive


LEGAL_SUFFIX = re.compile(r"\b(inc|llc|l\.?l\.?c|corp|corporation|company|ltd|"
                          r"limited|plc|co|holdings|group|gmbh|ab|sa|nv|pty)\b")


def _org_tokens(name: str) -> set[str]:
    return set(LEGAL_SUFFIX.sub(" ", re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())).split())


def _squash(name: str) -> str:
    """Letters and digits only, order kept: the same company written with
    different punctuation ("ON.energy" on its own board, "ONENERGY" from an
    aggregator) collapses to one string, while two different companies
    sharing a first word do not."""
    return "".join(_org_tokens_ordered(name))


def _org_tokens_ordered(name: str) -> list[str]:
    return LEGAL_SUFFIX.sub(" ", re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())).split()


def same_org(stated: str, company: str) -> bool:
    """Is the name the board states the same organization we meant?

    Deliberately NOT util.company_key, which collapses a name to its first
    word for cross-source twin matching ("Amazon.com Services LLC" ==
    "Amazon"). Under that rule "Hive Systems" == "HIVE Digital" and
    "Galaxy Security" == "Galaxy Digital" — the exact confusions this
    module exists to prevent. Here the whole name has to agree: equal token
    sets, or one a subset of the other so a board may state a longer legal
    name ("Bitdeer" vs "Bitdeer Technologies"), or the same letters in the
    same order once punctuation is dropped ("ON.energy" vs "ONENERGY").
    """
    a, b = _org_tokens(stated), _org_tokens(company)
    if not a or not b:
        return False
    if _squash(stated) == _squash(company):
        return True
    return a == b or a < b or b < a


def board_name(provider: str, slug: str) -> str | None:
    """The organization name the provider states for this board, or None
    when the provider publishes none (or the lookup fails)."""
    url = NAME_API.get(provider)
    if not url:
        return None
    try:
        time.sleep(0.25)
        resp = requests.get(url.format(slug=slug), headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return None
        return (resp.json().get("name") or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.debug("name lookup %s:%s failed: %s", provider, slug, e)
        return None


def identifies(provider: str, slug: str, company: str,
               board_titles: list[str], known: list[str]) -> bool:
    """Is this board that company's board? Stated identity settles it;
    otherwise the title evidence has to be strong enough to stand alone."""
    stated = board_name(provider, slug)
    if stated is not None:
        if same_org(stated, company):
            return True
        log.info("Rejected %s board %r for %s: it belongs to %r",
                 provider, slug, company, stated)
        return False

    n, exact, distinctive = title_evidence(board_titles, known)
    if n >= MIN_TITLE_MATCHES and exact and distinctive:
        return True
    log.info("Rejected %s board %r for %s: %s names no organization and the "
             "title evidence is thin (%d matched, exact=%s, distinctive=%s)",
             provider, slug, company, provider, n, exact, distinctive)
    return False


def discover(company: str, known_titles: list[str]) -> dict | None:
    for slug in slug_variants(company):
        for provider, (url, extract) in PROBES.items():
            try:
                time.sleep(0.25)
                resp = requests.get(url.format(slug=slug), headers=HEADERS, timeout=12)
                if resp.status_code != 200:
                    continue
                titles = extract(resp.json())
                if not titles:
                    continue
                if identifies(provider, slug, company, titles, known_titles):
                    log.info("Discovered %s board for %s: %s (%d postings)",
                             provider, company, slug, len(titles))
                    return {"provider": provider, "board": slug, "company": company}
            except Exception as e:  # noqa: BLE001
                log.debug("probe %s:%s failed: %s", provider, slug, e)
    return None


def _load_attempts() -> dict:
    if ATTEMPTS_FILE.exists():
        return json.loads(ATTEMPTS_FILE.read_text())
    return {}


def run(seen: dict, config: dict) -> list[dict]:
    """Probe boards for aggregator-only companies with strong/top roles.
    Returns config entries to add (caller persists them)."""
    from .state import AGGREGATOR_SOURCES
    direct = {company_key(e.get("company", ""))
              for key in ("ats_boards", "workday_boards", "successfactors_boards",
                          "career_sites")
              for e in config.get(key, [])}
    attempts = _load_attempts()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETRY_DAYS)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    by_company: dict[str, list[dict]] = {}
    for r in seen.values():
        if r.get("active", True) and r.get("company"):
            by_company.setdefault(r["company"], []).append(r)

    candidates = []
    for company, recs in by_company.items():
        if company_key(company) in direct:
            continue
        if not all(r.get("source") in AGGREGATOR_SOURCES for r in recs):
            continue
        if attempts.get(company_key(company), "") > cutoff:
            continue  # probed recently, nothing found
        strong = [r for r in recs if (r.get("score") or 0) >= STRONG_SCORE]
        if strong:
            # Best role first, not most roles: a single top-band posting is
            # as worth wiring up as six strong ones, and the big employers
            # that dominate a volume sort rarely use a standard ATS.
            candidates.append((max(r["score"] for r in strong), len(strong),
                               company, [r["title"] for r in recs]))
    candidates.sort(reverse=True)

    found = []
    for _, _, company, titles in candidates[:MAX_PER_RUN]:
        entry = discover(company, titles)
        attempts[company_key(company)] = today
        if entry:
            found.append(entry)
    ATTEMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ATTEMPTS_FILE.write_text(json.dumps(attempts, indent=1, sort_keys=True) + "\n")
    return found

"""Model-free tests for one-tap feedback verdicts and pay extraction.

Run: python -m pytest -q tests
"""
import pytest

from src import dashboard, feedback
from src.sources import successfactors
from src.state import _better_pay
from src.util import extract_pay


# --- pay ---------------------------------------------------------------

@pytest.mark.parametrize("text,pay", [
    # PG&E's three phrasings, from live postings on 2026-10-02.
    ("A reasonable salary range is: Bay Area Minimum: $126,000 Bay Area Maximum: $200,000 "
     "OR California Minimum: $120,000 California Maximum: $190,000", "$126,000–$200,000"),
    ("Minimum Base Salary (Bay Area) $140,000.00 Mid Base Salary (Bay Area) $189,000.00 "
     "Maximum Base Salary (Bay Area) $238,000.00", "$140,000–$238,000"),
    ("The annual salary range is: CA Minimum, $161,520 CA Maximum, $207,504", "$161,520–$207,504"),
    ("Pay range $150,000 - $200,000 per year", "$150,000 - $200,000 per year"),
    ("No pay stated.", ""),
    ("A reasonable salary range is: Bay Area Min: $147,000 Bay Area Mid: $199,000 Bay Area Max: $251,000",
     "$147,000–$251,000"),
    ("A reasonable salary range is: Bay Area Minimum: $\u200b122,000 Bay Area Maximum: $\u200b194,000",
     "$122,000–$194,000"),
    # PG&E puts the salary sentence well before the figures (live, 2026-10-01).
    ("PG&E is providing the salary range ... " + "x" * 400 +
     " Bay Area Minimum: $136,000 Bay Area Mid:$184,000 Bay Maximum: $232,000", "$136,000–$232,000"),
    # Review findings: units kept, and min/max outside a pay context ignored.
    ("Relocation: Minimum $5,000 offered. Salary: Minimum $100,000 Maximum $150,000",
     "$100,000–$150,000"),
    ("You will work across a wide range of projects. Minimum $5,000 signing bonus, "
     "Maximum $10,000. Pay range $150,000 - $200,000 per year", "$150,000 - $200,000 per year"),
    ("A reasonable salary range is: Minimum: $45.50 Maximum: $60.00 per hour", "$45.50–$60/hr"),
    ("Relocation: Minimum $5,000 and Maximum $10,000. Pay range $150,000 - $200,000 per year",
     "$150,000 - $200,000 per year"),
])
def test_extract_pay(text, pay):
    assert extract_pay(text) == pay


def test_a_range_replaces_a_single_figure_only():
    assert _better_pay("pay", "$126,000–$200,000", "$126,000")
    assert not _better_pay("pay", "$126,000", "$126,000–$200,000")
    assert not _better_pay("work_mode", "remote", "onsite")
    assert not _better_pay("pay", "$100,000 - $130,000", "$120K-$150K"), "k ranges are ranges"
    assert not _better_pay("pay", "$1 - $2", "$45/hr - $60/hr")


def test_successfactors_description_is_the_posting_not_the_page():
    html = ('<script>var junk = "$(document)";</script><div>Cookie banner</div>'
            '<span itemprop="description" class="jobdescription">Requisition ID # 1 '
            'A reasonable salary range is: Bay Area Minimum: $126,000 Bay Area Maximum: $200,000</span>'
            '<div id="similar-jobs">Other roles</div>')
    d = successfactors.page_description(html)
    assert d.startswith("Requisition ID") and "Cookie" not in d and "Other roles" not in d
    assert not d.endswith("<div"), "cut at the start of the end tag"
    assert successfactors.page_description(
        '<div itemprop="description"><p>Intro</p>Salary Minimum: $1 Maximum $2</main>'
    ).endswith("Maximum $2"), "text right before </main> is kept"
    assert successfactors.page_description(
        '<div itemprop="description"><div id="similar">x</div><p>body</p>') == "", \
        "an empty posting block yields nothing"
    head = '<head><meta itemprop="description" content="site blurb"></head>'
    assert successfactors.page_description(head + html).startswith("Requisition ID"), \
        "a <meta> description is not the posting"
    assert successfactors.page_description("<div>Cookie banner, menus, footer</div>") == "", \
        "a page with no posting block yields nothing, not site chrome"
    assert extract_pay(d) == "$126,000–$200,000"


# --- verdicts -------------------------------------------------------------

def _issue(number, body, title="feedback: Principal Electric Program Manager @ PG&E"):
    return {"number": number, "title": title, "body": body}


def test_verdict_issue_parses_and_stays_guidance(monkeypatch):
    rec = {"_id": "abc123", "band": "top", "rationale": "Program role."}
    body = dashboard._verdict_body(rec, "lower", "Too technical, belongs lower")
    monkeypatch.setattr(feedback, "_issue_entries", lambda: [_issue(7, body)])
    monkeypatch.setattr(feedback, "FILE", feedback.Path("/nonexistent"))
    fb = feedback.load()
    assert fb["verdicts"] == [{"issue": 7, "job_id": "abc123",
                               "target": "Principal Electric Program Manager @ PG&E",
                               "direction": "lower", "reason": "Too technical, belongs lower"}]
    assert "Reason: Too technical" in fb["text"]
    assert "Tap Create" not in fb["text"] and "Scored top" not in fb["text"]


def test_verdict_moves_one_band_once():
    seen = {"abc123": {"title": "Principal Electric Program Manager", "company": "PG&E",
                       "band": "top", "score": 90, "rationale": "Program role."}}
    v = [{"issue": 7, "job_id": "abc123", "target": "x", "direction": "lower",
          "reason": "Too technical, belongs lower"}]
    assert feedback.apply_verdicts(seen, v) == 1
    assert feedback.apply_verdicts(seen, v) == 0, "an issue applies once"
    rec = seen["abc123"]
    assert (rec["band"], rec["score"]) == ("strong", 75)
    assert rec["rationale"].startswith("Owner feedback (#7)")
    assert rec["scoring_fingerprint"]["owner"], "re-scoring must not overwrite it"

    up = [{"issue": 8, "job_id": "abc123", "target": "x", "direction": "higher", "reason": "Great fit"}]
    feedback.apply_verdicts(seen, up)
    feedback.apply_verdicts(seen, [{**up[0], "issue": 9}])
    assert seen["abc123"]["band"] == "top", "top is the ceiling"


def test_verdict_without_id_matches_the_exact_title_and_company_only():
    seen = {"a": {"title": "Principal Electric Program Manager", "company": "PG&E", "band": "strong"},
            "b": {"title": "Senior Principal Electric Program Manager", "company": "PG&E", "band": "strong"}}
    feedback.apply_verdicts(seen, [{"issue": 3, "job_id": None, "direction": "lower", "reason": "",
                                    "target": "Principal Electric Program Manager @ PG&E"}])
    assert seen["a"]["band"] == "possible" and seen["b"]["band"] == "strong"


def test_verdict_up_from_the_archive_restores_it():
    seen = {"a": {"title": "T", "company": "C", "band": "misfit", "active": False,
                  "lowscore": True, "closed": "2026-10-01"}}
    feedback.apply_verdicts(seen, [{"issue": 5, "job_id": "a", "direction": "higher", "reason": "",
                                    "target": "T @ C"}])
    assert seen["a"]["band"] == "weak" and seen["a"]["active"] and not seen["a"]["lowscore"]
    assert "closed" not in seen["a"]


def test_verdict_matches_a_title_the_dashboard_cut_at_80():
    long = "Senior Principal Program Manager, Electric Distribution Grid Modernization and Reliability Programs"
    seen = {"a": {"title": long, "company": "PG&E", "band": "strong"}}
    feedback.apply_verdicts(seen, [{"issue": 6, "job_id": None, "direction": "lower", "reason": "",
                                    "target": f"{long[:80]} @ PG&E"}])
    assert seen["a"]["band"] == "possible"


def test_verdict_down_to_misfit_archives_it():
    seen = {"a": {"title": "T", "company": "C", "band": "weak", "active": True}}
    feedback.apply_verdicts(seen, [{"issue": 4, "job_id": "a", "direction": "lower", "reason": "",
                                    "target": "T @ C"}])
    assert seen["a"]["band"] == "misfit" and seen["a"]["active"] is False and seen["a"]["lowscore"]


def test_dashboard_row_has_the_four_buttons():
    row = dashboard._row({"_id": "abc123", "title": "Role", "company": "Co", "band": "strong",
                          "score": 75, "url": "https://example.com"})
    for label in ("great fit", "too technical", "experience", "industry", "note"):
        assert label in row
    assert row.count('class="v"') == 4 and 'data-id="abc123"' in row and 'data-ref="Role @ Co"' in row
    js = dashboard._verdict_js()
    assert '"higher"' in js and js.count('"lower"') == 3 and "<!-- job: {job_id} -->" in js


# --- refreshing tracked records -----------------------------------------

def _job(**kw):
    from src.models import Job
    base = dict(title="Senior, Grid Innovation Engineer - Resiliency", company="PG&E",
                location="Oakland, CA", url="https://careers.pge.com/job/Oakland-x/1435999",
                source="successfactors")
    return Job(**{**base, **kw})


def test_screen_passes_tracked_postings_so_their_records_refresh(monkeypatch):
    """A screen-rescued posting fails the keyword filter on every later run;
    passing tracked postings through lets split_new refresh its pay."""
    from src import screen, state
    monkeypatch.setattr(screen, "load", lambda: {})
    monkeypatch.setattr(screen, "save", lambda s: None)
    monkeypatch.setattr(screen, "judge", lambda jobs: {})
    job = _job(pay="$122,000–$194,000")
    seen = {job.job_id: {"title": job.title, "company": "PG&E", "location": job.location,
                         "url": job.url, "source": "successfactors", "pay": "$122,000"}}
    hidden = _job(title="Hidden role", url="https://careers.pge.com/job/h/1")
    seen[hidden.job_id] = {"title": hidden.title, "company": "PG&E", "hidden": True}
    kept, _, _ = screen.apply([job, hidden], [], seen, {"title_exclusions": []})
    assert [j.job_id for j in kept] == [job.job_id], "tracked passes; hidden does not"
    assert state.split_new(kept, seen) == [], "tracked postings are not new, so never re-scored"
    assert seen[job.job_id]["pay"] == "$122,000–$194,000"


def test_merge_only_fills_or_upgrades_never_flips():
    from src import state
    job = _job(pay="$100,000–$160,000", work_mode="onsite")
    seen = {job.job_id: {"title": job.title, "company": "PG&E", "location": job.location,
                         "source": "successfactors", "pay": "$122,000–$194,000", "work_mode": "hybrid"}}
    state.split_new([job], seen)
    assert (seen[job.job_id]["pay"], seen[job.job_id]["work_mode"]) == ("$122,000–$194,000", "hybrid"), \
        "another metro's copy never replaces a stored range"
    state.split_new([_job(pay="$150,000")], seen)
    assert seen[job.job_id]["pay"] == "$122,000–$194,000", "a single figure never replaces a range"


def test_pay_backfill_reads_open_pages_and_retries_failed_loads(monkeypatch):
    class Resp:
        def __init__(self, text, ok=True): self.text, self.ok = text, ok
        def raise_for_status(self):
            if not self.ok: raise RuntimeError("503")
    pages = {"https://careers.pge.com/a": Resp("<div itemprop=\"description\">A reasonable salary range is: "
                                               "Bay Area Minimum: $122,000 Bay Area Maximum: $194,000</div>"),
             "https://careers.pge.com/b": Resp("<div>closed posting</div>"),
             "https://careers.pge.com/f": Resp("", ok=False)}
    calls = []
    monkeypatch.setattr(successfactors.requests, "get", lambda u, **k: calls.append(u) or pages[u])
    monkeypatch.setattr(successfactors.time, "sleep", lambda s: None)
    seen = {
        "a": {"source": "successfactors", "url": "https://careers.pge.com/a", "pay": "$122,000"},
        "b": {"source": "successfactors", "url": "https://careers.pge.com/b", "pay": ""},
        "f": {"source": "successfactors", "url": "https://careers.pge.com/f", "pay": ""},
        "c": {"source": "successfactors", "url": "https://careers.pge.com/c", "pay": "$1–$2"},  # has a range
        "d": {"source": "successfactors", "url": "https://careers.pge.com/d", "pay": "", "duplicate": True},
        "e": {"source": "successfactors", "url": "https://careers.pge.com/e", "pay": "", "active": False},
    }
    successfactors._desc_cache.clear()
    assert successfactors.backfill_pay(seen) == 1
    assert seen["a"]["pay"] == "$122,000–$194,000" and seen["a"]["pay_checked"]
    assert not seen["b"].get("pay_checked") and not seen["f"].get("pay_checked"), \
        "no posting block or a failed load: tried again next run"
    for _ in range(2):
        calls.clear()
        successfactors.backfill_pay(seen)
        assert sorted(calls) == ["https://careers.pge.com/b", "https://careers.pge.com/f"]
    assert seen["b"]["pay_checked"] and seen["f"]["pay_tries"] == 3, "three tries, then left alone"
    calls.clear()
    successfactors.backfill_pay(seen)
    assert calls == []


def test_pay_backfill_uses_pages_this_run_already_fetched(monkeypatch):
    url = "https://careers.pge.com/z"
    successfactors._desc_cache[url] = "A reasonable salary range is: Minimum: $1,000 Maximum: $2,000"
    monkeypatch.setattr(successfactors.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    seen = {"z": {"source": "successfactors", "url": url, "pay": ""}}
    assert successfactors.backfill_pay(seen) == 1 and seen["z"]["pay"] == "$1,000–$2,000"
    successfactors._desc_cache.pop(url)


def test_screen_passes_a_record_stored_under_another_copy(monkeypatch):
    from src import screen
    monkeypatch.setattr(screen, "load", lambda: {})
    monkeypatch.setattr(screen, "save", lambda s: None)
    judged = []
    monkeypatch.setattr(screen, "judge", lambda jobs: judged.extend(jobs) or {})
    stored = _job(location="Oakland, California")
    seen = {stored.job_id: {"title": stored.title, "company": "PG&E", "url": stored.url,
                            "source": "successfactors"}}
    today = _job(location="Oakland, CA")  # same employer posting id, other wording
    kept, _, _ = screen.apply([today], [], seen, {"title_exclusions": []})
    assert [j.job_id for j in kept] == [today.job_id] and judged == [], \
        "matched by the employer's posting id, so passed through and not judged again"

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
    for label in ("great fit", "too technical", "lack experience", "wrong industry", "other"):
        assert label in row
    assert "Verdict%3A%20higher" in row and row.count("Verdict%3A%20lower") == 3

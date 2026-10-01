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
])
def test_extract_pay(text, pay):
    assert extract_pay(text) == pay


def test_a_range_replaces_a_single_figure_only():
    assert _better_pay("pay", "$126,000–$200,000", "$126,000")
    assert not _better_pay("pay", "$126,000", "$126,000–$200,000")
    assert not _better_pay("work_mode", "remote", "onsite")


def test_successfactors_description_is_the_posting_not_the_page():
    html = ('<script>var junk = "$(document)";</script><div>Cookie banner</div>'
            '<span itemprop="description" class="jobdescription">Requisition ID # 1 '
            'Bay Area Minimum: $126,000 Bay Area Maximum: $200,000</span>'
            '<div id="similar-jobs">Other roles</div>')
    d = successfactors.page_description(html)
    assert d.startswith("Requisition ID") and "Cookie" not in d and "Other roles" not in d
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


def test_verdict_without_id_matches_by_title_and_company():
    seen = {"a": {"title": "Principal Electric Program Manager", "company": "PG&E", "band": "strong"},
            "b": {"title": "Grid Innovation Engineer", "company": "PG&E", "band": "strong"}}
    feedback.apply_verdicts(seen, [{"issue": 3, "job_id": None, "direction": "lower", "reason": "",
                                    "target": "Principal Electric Program Manager @ PG&E"}])
    assert seen["a"]["band"] == "possible" and seen["b"]["band"] == "strong"


def test_dashboard_row_has_the_four_buttons():
    row = dashboard._row({"_id": "abc123", "title": "Role", "company": "Co", "band": "strong",
                          "score": 75, "url": "https://example.com"})
    for label in ("great fit", "too technical", "lack experience", "wrong industry", "other"):
        assert label in row
    assert "Verdict%3A%20higher" in row and row.count("Verdict%3A%20lower") == 3

"""Model-free tests for the links people click and dashboard ordering.

Run: python -m pytest -q tests
"""
import pytest

from src import dashboard
from src.util import best_link

INDEED = "https://www.indeed.com/viewjob?jk=4a925ea946d75f8d"
GOOGLE = "https://careers.google.com/jobs/results/122925809672299206-senior-product-manager/"


def test_indeed_posting_shows_the_employer_link():
    """The 2026-09-30 Google Research posting: digest and dashboard linked
    Indeed although the employer's own link was on the record."""
    rec = {"source": "indeed", "url": INDEED, "apply_url": GOOGLE}
    assert best_link(rec) == GOOGLE
    assert rec["url"] == INDEED, "expiry still reads the Indeed listing"


@pytest.mark.parametrize("rec", [
    {"source": "indeed", "url": INDEED},                                   # no link
    {"source": "indeed", "url": INDEED, "apply_url": None},
    {"source": "indeed", "url": INDEED, "apply_url": "https://www.indeed.com/applystart?jk=1"},
    {"source": "indeed", "url": INDEED, "apply_url": "https://www.linkedin.com/jobs/view/1"},
    {"source": "greenhouse", "url": "https://job-boards.greenhouse.io/a/jobs/1",
     "apply_url": GOOGLE},                                                 # direct source wins
])
def test_otherwise_the_stored_link_is_shown(rec):
    assert best_link(rec) == rec["url"]


@pytest.mark.parametrize("score,band", [
    (92, "top"), (85, "top"), (82, "strong"), (76, "strong"), (60, "possible"), (68, "strong"),
    (40, "weak"), (10, "misfit"),
])
def test_pre_band_scores_take_the_nearest_band(score, band):
    assert dashboard._band({"score": score}) == band


def test_new_strong_posting_is_not_buried_under_old_numeric_scores():
    old = {f"o{i}": {"score": 82, "first_seen": "2026-08-20", "active": True}
           for i in range(5)}
    new = {"n": {"score": 75, "band": "strong", "first_seen": "2026-09-01", "active": True}}
    shown, _, _ = dashboard._select_rows({**old, **new}, max_rows=3)
    assert shown[0] is new["n"], "same band, so the newer posting ranks first"
    assert 'data-s="75"' in dashboard._row(old["o0"]), "an old 82 sorts as strong"

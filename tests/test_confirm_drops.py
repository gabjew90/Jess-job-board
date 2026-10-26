"""Model-free tests for the drop check: a re-score that buries a top or
strong record is scored once more and the median band is kept.

Run: python -m pytest -q tests
"""
from src import triage
from src.models import Job


def _job(t):
    return Job(title=t, company="Co", location="US", url=f"https://x/{t}", source="indeed")


def _r(band):
    return {"band": band, "score": triage.BAND_SCORE[band], "rationale": f"said {band}",
            "seniority_match": True}


def test_noise_drop_keeps_prior_band(monkeypatch):
    j = _job("a")
    scores = {j.job_id: _r("possible")}
    monkeypatch.setattr(triage, "score", lambda jobs, fb="": {j.job_id: _r("top")})
    prior = {j.job_id: {"band": "top", "score": 90, "rationale": "old call"}}
    assert triage.confirm_drops([j], scores, prior) == 1
    assert scores[j.job_id]["band"] == "top" and scores[j.job_id]["score"] == 90
    assert scores[j.job_id]["rationale"] == "said top", "the current answer's reasoning stands"


def test_repeated_drop_is_kept(monkeypatch):
    j = _job("b")
    scores = {j.job_id: _r("weak")}
    monkeypatch.setattr(triage, "score", lambda jobs, fb="": {j.job_id: _r("possible")})
    triage.confirm_drops([j], scores, {j.job_id: {"band": "strong"}})
    assert scores[j.job_id]["band"] == "possible"


def test_small_moves_and_low_priors_are_not_rechecked(monkeypatch):
    a, b = _job("c"), _job("d")
    scores = {a.job_id: _r("strong"), b.job_id: _r("misfit")}
    monkeypatch.setattr(triage, "score", lambda jobs, fb="": (_ for _ in ()).throw(AssertionError("no call")))
    assert triage.confirm_drops([a, b], scores, {a.job_id: {"band": "top"}, b.job_id: {"band": "weak"}}) == 0


def test_possible_dropping_to_misfit_is_rechecked(monkeypatch):
    j = _job("g")
    scores = {j.job_id: _r("misfit")}
    monkeypatch.setattr(triage, "score", lambda jobs, fb="": {j.job_id: _r("possible")})
    assert triage.confirm_drops([j], scores, {j.job_id: {"band": "possible"}}) == 1
    assert scores[j.job_id]["band"] == "possible"


def test_second_answer_lower_than_first_takes_the_first(monkeypatch):
    j = _job("e")
    scores = {j.job_id: _r("possible")}
    monkeypatch.setattr(triage, "score", lambda jobs, fb="": {j.job_id: _r("misfit")})
    triage.confirm_drops([j], scores, {j.job_id: {"band": "top"}})
    assert scores[j.job_id]["band"] == "possible"


def test_no_second_answer_leaves_the_first(monkeypatch):
    j = _job("f")
    scores = {j.job_id: _r("weak")}
    monkeypatch.setattr(triage, "score", lambda jobs, fb="": {})
    triage.confirm_drops([j], scores, {j.job_id: {"band": "strong"}})
    assert scores[j.job_id]["band"] == "weak"


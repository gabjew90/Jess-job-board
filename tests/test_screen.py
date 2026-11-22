"""Model-free tests for the title screen's bookkeeping and the code-side
scoring policy. The model call itself (screen.judge / triage.score) is
stubbed; what is under test is what the pipeline does with the verdicts.

Run: python -m pytest -q tests
"""
import json

import pytest

from src import screen, triage
from src.models import Job


def job(title="Director, Power Infrastructure", company="Acme", url=None):
    return Job(title=title, company=company, location="US",
               url=url or f"https://x/{title}", source="greenhouse",
               description="power infrastructure strategy")


CONFIG = {"title_exclusions": [], "priority_topics": [],
          "rescue_title_keywords": ["director"]}


@pytest.fixture
def memory(tmp_path, monkeypatch):
    """Isolate state/screened_out.json."""
    path = tmp_path / "screened_out.json"
    monkeypatch.setattr(screen, "FILE", path)
    return path


def test_remembered_drop_is_binding_on_later_runs(memory, monkeypatch):
    """The leak this fixes: the screen drops a keyword pass, remembers it,
    and on the next run it is skipped for re-judging but was still handed
    on for scoring."""
    j = job()
    monkeypatch.setattr(screen, "judge", lambda jobs: {j.job_id: False})
    kept, rejected, stats = screen.apply([j], [j], {}, CONFIG)
    assert kept == [] and [r.job_id for r in rejected] == [j.job_id]
    assert stats["dropped"] == 1 and stats["held"] == 0
    assert json.loads(memory.read_text()).get(j.job_id)

    # Run two: same posting, still passing the keyword filter. It must not
    # be re-judged (costly) and must not reach scoring (the bug).
    def no_rejudge(jobs):
        assert not jobs, "re-judged a remembered drop (a paid model call)"
        return {}
    monkeypatch.setattr(screen, "judge", no_rejudge)
    kept, rejected, stats = screen.apply([j], [j], {}, CONFIG)
    assert kept == []
    assert stats["held"] == 1


def test_remembered_drop_binds_even_when_the_screen_is_unavailable(memory, monkeypatch):
    j = job()
    screen.save({j.job_id: "2099-01-01"})
    monkeypatch.setattr(screen, "judge", lambda jobs: {})  # CLI down / all chunks failed
    kept, _, stats = screen.apply([j], [j], {}, CONFIG)
    assert kept == [] and stats["held"] == 1


def test_unremembered_posting_still_flows_through(memory, monkeypatch):
    j, other = job(), job(title="Director, Grid Strategy")
    screen.save({j.job_id: "2099-01-01"})
    monkeypatch.setattr(screen, "judge", lambda jobs: {other.job_id: True})
    kept, _, stats = screen.apply([j, other], [j, other], {}, CONFIG)
    assert [k.job_id for k in kept] == [other.job_id]
    assert stats["held"] == 1


def test_expired_memory_lets_a_posting_back_in(memory, monkeypatch):
    j = job()
    screen.save({j.job_id: "2000-01-01"})  # older than RETENTION_DAYS: pruned on save
    assert screen.load() == {}
    monkeypatch.setattr(screen, "judge", lambda jobs: {j.job_id: True})
    kept, _, stats = screen.apply([j], [j], {}, CONFIG)
    assert [k.job_id for k in kept] == [j.job_id] and stats["held"] == 0


def test_seniority_cap_is_applied_by_triage_not_the_caller():
    """The cap used to live in main.py, so the eval graded a band no record
    ever carried. finalize() is the single definition of the final band."""
    capped = triage.finalize({"band": "top", "score": 90, "seniority_match": False})
    assert capped["band"] == "weak" and capped["score"] == triage.BAND_SCORE["weak"]

    for band in ("misfit", "weak"):
        rec = {"band": band, "score": triage.BAND_SCORE[band], "seniority_match": False}
        assert triage.finalize(dict(rec)) == rec  # already at or below the cap

    passed = {"band": "top", "score": 90, "seniority_match": True}
    assert triage.finalize(dict(passed)) == passed


def test_score_returns_final_bands(monkeypatch):
    j = job()
    monkeypatch.setattr(triage, "available", lambda: True)
    monkeypatch.setattr(triage, "_score_chunk", lambda chunk, p, f: {
        j.job_id: {"band": "strong", "score": 75, "rationale": "", 
                   "seniority_match": False, "pay": "", "work_mode": ""}})
    out = triage.score([j], "")
    assert out[j.job_id]["band"] == "weak", "score() must return the band that ships"


def test_fingerprint_tracks_the_policy_not_just_the_rubric(monkeypatch):
    before = triage.scoring_fingerprint("fb")
    monkeypatch.setattr(triage, "POLICY_VERSION", triage.POLICY_VERSION + 1)
    after = triage.scoring_fingerprint("fb")
    assert before["rubric"] == after["rubric"]
    assert before["policy"] != after["policy"], "a policy change must change the fingerprint"


def test_screen_eval_cases_are_well_formed():
    data = json.loads(screen.Path("eval/screen_cases.json").read_text())["cases"]
    assert len({c["id"] for c in data}) == len(data), "duplicate case ids"
    for c in data:
        assert c["title"] and c["company"] and c["reason"]
        assert isinstance(c["expected_keep"], bool)
    # Starts empty for a fresh watcher; once cases exist the set must cover
    # both polarities, or the screen eval only ever proves one direction.
    if data:
        assert any(c["expected_keep"] for c in data), "no keep case"
        assert any(not c["expected_keep"] for c in data), "no drop case"


def test_target_employer_keyword_pass_is_never_dropped(memory, monkeypatch):
    """Anthropic's "Data Center Power Generation and Microgrids Engineer"
    passed the keyword filter, was dropped on its title, and the owner
    applied to it from elsewhere (2026-10-30)."""
    cfg = {**CONFIG, "target_employers": ["Anthropic"]}
    role = job("Data Center Power Generation and Microgrids Engineer", "Anthropic")
    other = job("Data Center Electrical Engineer", "Acme")
    monkeypatch.setattr(screen, "judge", lambda jobs: {j.job_id: False for j in jobs})
    kept, rejected, stats = screen.apply([role, other], [role, other], {}, cfg)
    assert [k.job_id for k in kept] == [role.job_id]
    assert [r.job_id for r in rejected] == [other.job_id]
    assert "Data Center Electrical Engineer @ Acme" in json.loads(memory.read_text())[other.job_id], \
        "a drop is remembered with its title, so it can be audited"


def test_a_remembered_drop_at_a_target_employer_no_longer_holds(memory, monkeypatch):
    role = job("Data Center Power Generation and Microgrids Engineer", "Anthropic")
    screen.save({role.job_id: "2099-01-01"})
    monkeypatch.setattr(screen, "judge", lambda jobs: {})
    kept, _, stats = screen.apply([role], [role], {}, {**CONFIG, "target_employers": ["Anthropic"]})
    assert [k.job_id for k in kept] == [role.job_id] and stats["held"] == 0


def test_pay_floor_caps_a_full_range_below_it_only():
    rec = lambda pay, band="strong", **kw: {"band": band, "score": 75, "pay": pay, **kw}  # noqa: E731
    low = rec("$113,000–$165,000/yr")
    assert triage.pay_cap(low, 170000) and low["band"] == "possible" and low["pay_capped"] == "strong"
    assert not triage.pay_cap(rec("$150,000–$180,000/yr"), 170000)
    assert not triage.pay_cap(rec("$162,700"), 170000), "a single figure is often the floor"
    assert not triage.pay_cap(rec("$45–$60/hr", "possible"), 170000)
    assert not triage.pay_cap(rec("$100,000–$120,000", scoring_fingerprint={"owner": "x"}), 170000)
    assert not triage.pay_cap(rec("$100,000–$120,000"), 0), "no floor configured"


def test_pay_parsing_reads_the_whole_range():
    from src.util import pay_max_yearly as top
    assert top("$150,000 - 190,000") == 190000 and top("$160-190K") == 190000
    assert top("USD $00,000 - 00,000/annum") is None
    assert top("$85K–$95K annually + daily per diem") == 95000


def test_a_capped_record_is_restored_when_the_floor_no_longer_applies():
    rec = {"band": "top", "score": 90, "pay": "$120,000–$150,000/yr"}
    assert triage.pay_cap(rec, 170000) and rec["band"] == "possible"
    assert not triage.pay_cap(rec, 0) and rec["band"] == "top" and "pay_capped" not in rec

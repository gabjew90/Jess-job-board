"""Model-free tests for finding direct boards from employer apply links.

Run: python -m pytest -q tests
"""
import json

import pytest

from src import discovery, notify, state
from src.models import Job


# --- reading a board off an apply link --------------------------------

@pytest.mark.parametrize("url,kind,entry", [
    # Real links Indeed passed through on 2026-09-24.
    ("https://talenenergy.wd1.myworkdayjobs.com/en-US/TalenCareers/job/Houston-TX/Director_R1",
     "workday_boards", {"host": "talenenergy.wd1.myworkdayjobs.com",
                        "tenant": "talenenergy", "site": "TalenCareers"}),
    ("https://aep.wd1.myworkdayjobs.com/AEPCareerSite/job/Ft-Wayne-IN/Mechanic_R19418",
     "workday_boards", {"host": "aep.wd1.myworkdayjobs.com",
                        "tenant": "aep", "site": "AEPCareerSite"}),
    ("https://iberdrola.wd3.myworkdayjobs.com/en-US/Iberdrola/job/Orange/Supervisor_R1",
     "workday_boards", {"host": "iberdrola.wd3.myworkdayjobs.com",
                        "tenant": "iberdrola", "site": "Iberdrola"}),
    ("https://job-boards.greenhouse.io/Aligned/jobs/123",
     "ats_boards", {"provider": "greenhouse", "board": "aligned"}),
    ("https://boards.greenhouse.io/embed/job_app?for=veir&token=55",
     "ats_boards", {"provider": "greenhouse", "board": "veir"}),
    ("https://jobs.lever.co/acme/abc-123/apply",
     "ats_boards", {"provider": "lever", "board": "acme"}),
    ("https://jobs.ashbyhq.com/crusoe/9f1e",
     "ats_boards", {"provider": "ashby", "board": "crusoe"}),
])
def test_board_from_apply_link(url, kind, entry):
    got = discovery.board_from_url(url, "Acme")
    assert got == (kind, {**entry, "company": "Acme"})


@pytest.mark.parametrize("url", [
    "", "https://www.indeed.com/viewjob?jk=1",
    "https://careers.example.com/job/123",
    "https://talenenergy.wd1.myworkdayjobs.com/en-US/job/Houston-TX/x",  # no site
])
def test_links_we_cannot_read_give_no_board(url):
    assert discovery.board_from_url(url, "Acme") is None


def test_verify_linked_needs_one_known_role(monkeypatch):
    entry = {"provider": "lever", "board": "acme", "company": "Acme"}
    monkeypatch.setattr(discovery, "board_titles",
                        lambda k, e, known: ["Director, Origination", "Technician"])
    assert discovery.verify_linked("ats_boards", entry, ["Director, Origination"])
    assert not discovery.verify_linked("ats_boards", entry, ["Plant Manager"])

    def boom(*a):
        raise RuntimeError("404")
    monkeypatch.setattr(discovery, "board_titles", boom)
    assert not discovery.verify_linked("ats_boards", entry, ["Director, Origination"])


# --- stated names that only contain ours -----------------------------

def test_a_contained_name_needs_a_shared_role(monkeypatch):
    """Live misfires on 2026-09-25: both boards state a name contained in
    ours, and neither lists anything the company posts."""
    monkeypatch.setattr(discovery, "board_name", lambda p, s: "NATIONAL")
    pr_firm = ["Director, Corporate Communications", "Director, Public Affairs"]
    assert not discovery.identifies("greenhouse", "national", "National Grid",
                                    pr_firm, ["Director, Grid Modernization"])
    monkeypatch.setattr(discovery, "board_name", lambda p, s: "Clearway Group")
    assert not discovery.identifies("greenhouse", "clearway", "Clearway Energy",
                                    ["Vacant Property Inspector"], ["Director, Origination"])

    # A legal-name difference with a role in common still identifies.
    monkeypatch.setattr(discovery, "board_name", lambda p, s: "Bitdeer")
    assert discovery.identifies("greenhouse", "bitdeer", "Bitdeer Technologies Group",
                                ["Data Center Manager"], ["Data Center Manager"])


# --- the run ----------------------------------------------------------

TALEN = "https://talenenergy.wd1.myworkdayjobs.com/en-US/TalenCareers/job/X/Dir_R1"


def rec(company, title, score=90, apply_url="", source="indeed"):
    return {"company": company, "title": title, "score": score,
            "source": source, "active": True, "apply_url": apply_url}


@pytest.fixture
def attempts(tmp_path, monkeypatch):
    path = tmp_path / "discovery_attempts.json"
    monkeypatch.setattr(discovery, "ATTEMPTS_FILE", path)
    monkeypatch.setattr(discovery, "discover", lambda c, t: None)  # no guessing
    return path


def test_linked_board_is_wired_as_workday(attempts, monkeypatch):
    monkeypatch.setattr(discovery, "verify_linked", lambda k, e, t: True)
    seen = {"1": rec("Talen Energy", "Director, Development", apply_url=TALEN)}
    found, unresolved = discovery.run(seen, {"indeed_company_watch": ["Talen Energy"]})
    assert unresolved == []
    assert found[0]["kind"] == "workday_boards"
    assert found[0]["entry"]["site"] == "TalenCareers"
    assert found[0]["board"] == "talenenergy/TalenCareers"


def test_failed_probe_is_reported_and_remembered(attempts, monkeypatch):
    monkeypatch.setattr(discovery, "verify_linked", lambda k, e, t: False)
    seen = {"1": rec("Talen Energy", "Director, Development", apply_url=TALEN),
            "2": rec("Talen Energy", "Plant Manager", score=75)}
    found, unresolved = discovery.run(seen, {})
    assert found == []
    assert unresolved == [{"company": "Talen Energy", "score": 90,
                           "title": "Director, Development"}]
    saved = json.loads(attempts.read_text())["talen energy"]
    assert saved["boards"] == ["workday:talenenergy.wd1.myworkdayjobs.com/talencareers"]

    # Same evidence next run: waits out RETRY_DAYS, so no repeat report.
    assert discovery.run(seen, {}) == ([], [])

    # A posting linking a board not yet tried is new evidence.
    seen["3"] = rec("Talen Energy", "VP Origination",
                    apply_url="https://jobs.lever.co/talen/1")
    _, unresolved = discovery.run(seen, {})
    assert [u["company"] for u in unresolved] == ["Talen Energy"]


def test_a_failed_link_is_retried_after_the_wait(attempts, monkeypatch):
    monkeypatch.setattr(discovery, "verify_linked", lambda k, e, t: False)
    seen = {"1": rec("Talen Energy", "Director, Development", apply_url=TALEN)}
    discovery.run(seen, {})
    saved = json.loads(attempts.read_text())
    saved["talen energy"]["date"] = "2000-01-01"
    attempts.write_text(json.dumps(saved))
    checked = []
    monkeypatch.setattr(discovery, "verify_linked", lambda k, e, t: checked.append(e) or True)
    found, _ = discovery.run(seen, {})
    assert checked and found[0]["company"] == "Talen Energy"


def test_retry_memory_uses_the_whole_name(attempts):
    """A failed probe for one "American ..." company must not silence another."""
    discovery.run({"1": rec("American Electric Power", "Director, Projects")}, {})
    _, unresolved = discovery.run({"2": rec("American Tower", "Director, Energy")}, {})
    assert [u["company"] for u in unresolved] == ["American Tower"]


def test_old_first_word_entries_are_dropped(attempts):
    attempts.write_text(json.dumps({"american": "2099-01-01"}))
    _, unresolved = discovery.run({"1": rec("American Electric Power", "Director")}, {})
    assert unresolved, "a legacy entry must not block the company"


def test_link_to_an_already_tracked_board_is_covered(attempts, monkeypatch):
    monkeypatch.setattr(discovery, "verify_linked",
                        lambda *a: pytest.fail("a tracked board needs no check"))
    config = {"workday_boards": [{"host": "iberdrola.wd3.myworkdayjobs.com",
                                  "tenant": "iberdrola", "site": "Iberdrola",
                                  "company": "Iberdrola"}]}
    link = "https://iberdrola.wd3.myworkdayjobs.com/en-US/Iberdrola/job/X/Y_R1"
    found, unresolved = discovery.run({"1": rec("Avangrid", "Director", apply_url=link)},
                                      config)
    assert (found, unresolved) == ([], [])


def test_companies_with_a_direct_posting_are_not_candidates(attempts):
    seen = {"1": rec("Acme", "Director", source="indeed"),
            "2": rec("Acme", "Manager", source="greenhouse")}
    assert discovery.run(seen, {}) == ([], [])


# --- apply links reach state ------------------------------------------

def test_apply_link_is_stored_and_backfilled():
    job = Job("Director", "Talen Energy", "Houston, TX", "https://indeed.com/1",
              "indeed", apply_url=TALEN)
    seen: dict = {}
    state.split_new([job], seen)
    assert seen[job.job_id]["apply_url"] == TALEN

    seen[job.job_id]["apply_url"] = ""        # a record stored before the field
    state.split_new([job], seen)
    assert seen[job.job_id]["apply_url"] == TALEN


# --- digest -----------------------------------------------------------

def test_digest_lists_unresolved_best_first():
    body = notify.build_digest(
        [], health_summary=[],
        unresolved=[{"company": "SRP", "score": 75, "title": "Origination"},
                    {"company": "RWE", "score": 90, "title": "Project Dev Manager"}])
    assert "No direct board found" in body
    assert "name one in chat" not in body
    assert body.index("RWE") < body.index("SRP")

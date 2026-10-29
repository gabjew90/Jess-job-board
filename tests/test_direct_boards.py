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

def test_unresolved_boards_show_in_any_digest():
    # Each company is probed once per 30 days, so its run is its one mention.
    body = notify.build_digest([], health_summary=[],
                               unresolved=[{"company": "SRP", "score": 75, "title": "Origination"}])
    assert "SRP" in body and "75" not in body


def test_digest_lists_unresolved_best_first():
    body = notify.build_digest(
        [], health_summary=[],
        unresolved=[{"company": "SRP", "score": 75, "title": "Origination"},
                    {"company": "RWE", "score": 90, "title": "Project Dev Manager"}])
    assert "No careers page found" in body and "75" not in body
    assert "name one in chat" not in body
    assert body.index("RWE") < body.index("SRP")


def test_footer_link_is_not_glued_to_markdown():
    body = notify.build_digest([], health_summary=[])
    assert f"]({notify.dashboard_url()})" in body.splitlines()[-1]
    assert f"{notify.dashboard_url()}_" not in body


def test_pages_404_sends_mangled_links_to_the_board():
    from pathlib import Path
    from src.dashboard import REPO
    page = (Path(__file__).parent.parent / "docs" / "404.html").read_text()
    owner, _, name = REPO.partition("/")
    assert page.count(f"https://{owner}.github.io/{name}/") == 3   # refresh, script, link


# --- Workday posted dates ---------------------------------------------

def test_workday_posted_on_becomes_a_date():
    from datetime import datetime, timedelta, timezone
    from src.sources.workday import posted_date
    day = lambda n: (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")
    assert posted_date("Posted Today") == day(0)
    assert posted_date("Posted Yesterday") == day(1)
    assert posted_date("Posted 4 Days Ago") == day(4)
    assert posted_date("Posted 30+ Days Ago") == ""   # no date to give
    assert posted_date("") == ""


# --- QA pass 2026-10-29 -----------------------------------------------

def test_company_key_keeps_generic_first_words_apart():
    from src.util import company_key
    assert company_key("Black & Veatch") != company_key("Black Hills Corporation")
    assert company_key("National Grid") != company_key("National Power, LLC")
    assert company_key("Vantage Data Centers") == company_key("Vantage")
    assert company_key("Hitachi Energy") == company_key("Hitachi")
    assert company_key("Black and Veatch") == company_key("Black & Veatch")
    assert company_key("American Electric Power (AEP)") == company_key("American Electric Power Service")
    assert company_key("The Boeing Company") == company_key("Boeing")


def test_a_new_employer_with_a_shared_first_word_is_not_swallowed():
    from src import state
    seen: dict = {}
    bv = Job("Project Manager", "Black & Veatch", "Kansas City, MO", "https://x/1", "indeed")
    bh = Job("Project Manager", "Black Hills Corporation", "Rapid City, SD", "https://x/2", "indeed")
    state.split_new([bv], seen)
    assert [j.job_id for j in state.split_new([bh], seen)] == [bh.job_id]


def test_a_relisted_posting_reopens_but_a_stale_aggregator_copy_does_not():
    from src import state
    seen: dict = {}
    job = Job("Director", "Acme", "Denver, CO", "https://jobs.lever.co/acme/1", "lever")
    state.split_new([job], seen)
    seen[job.job_id].update(active=False, closed="2026-01-01")
    copy = Job("Director", "Acme", "Austin, TX", "https://www.indeed.com/viewjob?jk=9", "indeed")
    state.split_new([copy], seen)
    assert not seen[job.job_id]["active"], "an aggregator's word never reopens a posting"
    state.split_new([job], seen)
    assert seen[job.job_id]["active"] and "closed" not in seen[job.job_id]
    seen[job.job_id].update(active=False, closed="2026-01-01", owner_closed=True)
    state.split_new([job], seen)
    assert not seen[job.job_id]["active"], "the owner's closed verdict stands"


def test_prune_keeps_open_postings_however_old():
    from src import state
    seen = {"old-open": {"first_seen": "2025-01-01", "active": True},
            "old-closed": {"first_seen": "2025-01-01", "active": False, "closed": "2025-02-01"},
            "recently-closed": {"first_seen": "2025-01-01", "active": False, "closed": "2099-01-01"}}
    assert set(state.prune(seen, 180)) == {"old-open", "recently-closed"}


def test_digest_escapes_brackets_cut_titles_and_blank_companies():
    r = {"title": "Senior Project Engineer [Hybride] | Senior Project Engineer [Hybrid] Extra",
         "company": "", "location": "Denver, CO", "url": "https://x/1", "band": "possible",
         "score": 55, "first_seen": "2026-10-01", "active": True}
    body = notify.build_digest([r], health_summary=[], window_hours=48)
    line = next(ln for ln in body.splitlines() if ln.startswith("- [Senior"))
    assert "\\[Hybr" in line and "· ·" not in line and line.endswith("Denver, CO")
    assert "in the last 48h" in body


def test_one_quiet_board_is_not_a_source_issue():
    health = [{"source": "workday:blackstone", "status": "empty", "error": None, "last_results": None},
              {"source": "greenhouse:veir", "status": "failed", "error": "403", "last_results": None},
              {"source": "indeed", "status": "empty", "error": None, "last_results": None}]
    body = notify.build_digest([], health_summary=health)
    health.append({"source": "jobspy:indeed", "status": "empty", "error": None, "last_results": None})
    body = notify.build_digest([], health_summary=health)
    assert "blackstone" not in body and "greenhouse:veir" in body and "`indeed`" in body
    assert "jobspy:indeed" in body, "an empty job-site feed is a likely block"


def test_relisting_after_the_owner_closed_it_is_a_new_opening():
    from src import state
    seen: dict = {}
    den = Job("Project Manager", "Acme", "Denver, CO", "https://jobs.lever.co/acme/1", "lever")
    state.split_new([den], seen)
    seen[den.job_id].update(active=False, closed="2026-01-01", owner_closed=True)
    aus = Job("Project Manager", "Acme", "Austin, TX", "https://jobs.lever.co/acme/2", "lever")
    assert [j.job_id for j in state.split_new([aus], seen)] == [aus.job_id]


def test_a_search_and_probe_source_never_reopens():
    from src import state
    seen: dict = {}
    job = Job("Director", "Acme", "Denver, CO", "https://acme.wd1.myworkdayjobs.com/x/job/1", "workday")
    state.split_new([job], seen)
    seen[job.job_id].update(active=False, closed="2026-01-01")
    state.split_new([job], seen)
    assert not seen[job.job_id]["active"], "its own probe found it gone; the search index lags"


def test_city_and_state_employers_keep_apart():
    from src.util import company_key
    assert company_key("City of Austin") != company_key("City of Denver")
    assert company_key("New York Power Authority") != company_key("New York Independent System Operator")


def test_a_board_that_went_empty_recently_is_still_a_source_issue():
    from datetime import date
    today = date.today().isoformat()
    body = notify.build_digest([], health_summary=[
        {"source": "greenhouse:veir", "status": "empty", "error": None, "last_results": today}])
    assert "greenhouse:veir" in body

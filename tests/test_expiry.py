"""Model-free tests for the expiry sweep: snapshot diff for full-list
sources, per-source liveness probes for the rest, and no timer anywhere.

Run: python -m pytest -q tests
"""
import pytest

from src import expiry, health
from src.models import Job


def rec(source, url="https://x/1", **kw):
    base = {"active": True, "source": source, "url": url, "title": "Director, Power",
            "company": "Acme", "location": "US", "first_seen": "2020-01-01",
            "date_posted": "2020-01-01"}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(expiry.time, "sleep", lambda s: None)
    monkeypatch.setattr(health, "_current", {})
    monkeypatch.setattr(expiry, "PROBES", dict(expiry.PROBES))
    monkeypatch.setattr(expiry, "_indeed_expired", lambda keys: {})


def test_no_timer_old_unprobed_posting_stays_open():
    seen = {"a": rec("meta", first_seen="2019-01-01", date_posted="2019-01-01")}
    closed = expiry.sweep(seen, [], {})
    assert closed == [] and seen["a"]["active"] is True


def test_full_list_provider_diff_closes_only_when_healthy():
    health.record("edged:all", ok=True, count=5)
    seen = {"gone": rec("edged"), "kept": rec("edged", title="Kept role")}
    present = [Job(title="Kept role", company="Acme", location="US",
                   url="https://x/k", source="edged")]
    seen["kept"]["url"] = present[0].url
    expiry.sweep({"kept": seen["kept"], present[0].job_id: seen["kept"]} | {"gone": seen["gone"]}, present, {})
    assert seen["gone"]["active"] is False and seen["kept"]["active"] is True

    health._current.clear()
    health.record("edged:all", ok=False, error="boom")
    again = {"gone2": rec("edged")}
    expiry.sweep(again, [], {})
    assert again["gone2"]["active"] is True  # outage: nothing expires


def test_probe_closes_only_on_definitive_no(monkeypatch):
    verdicts = {"dead": False, "alive": True, "unknown": None}
    monkeypatch.setitem(expiry.PROBES, "workday", lambda r: verdicts[r["url"]])
    seen = {k: rec("workday", url=k) for k in verdicts}
    closed = expiry.sweep(seen, [], {})
    assert [r["url"] for r in closed] == ["dead"]
    assert seen["alive"]["active"] and seen["unknown"]["active"]
    assert seen["dead"]["active"] is False and seen["dead"]["closed"]


def test_indeed_batch_expired_or_forgotten_closes(monkeypatch):
    monkeypatch.setattr(expiry, "_indeed_expired",
                        lambda keys: {"aaaaaaaaaaaaaaaa": False, "bbbbbbbbbbbbbbbb": True})
    seen = {"open": rec("indeed", url="https://www.indeed.com/viewjob?jk=aaaaaaaaaaaaaaaa"),
            "expired": rec("indeed", url="https://www.indeed.com/viewjob?jk=bbbbbbbbbbbbbbbb"),
            "forgotten": rec("indeed", url="https://www.indeed.com/viewjob?jk=cccccccccccccccc")}
    expiry.sweep(seen, [], {})
    assert seen["open"]["active"] is True
    assert seen["expired"]["active"] is False and seen["forgotten"]["active"] is False


def test_indeed_api_unavailable_closes_nothing(monkeypatch):
    monkeypatch.setattr(expiry, "_indeed_expired", lambda keys: None)
    seen = {"a": rec("indeed", url="https://www.indeed.com/viewjob?jk=aaaaaaaaaaaaaaaa")}
    assert expiry.sweep(seen, [], {}) == [] and seen["a"]["active"] is True


def test_suspect_probe_closes_nothing(monkeypatch):
    monkeypatch.setitem(expiry.PROBES, "successfactors", lambda r: False)
    seen = {str(i): rec("successfactors", url=f"https://x/{i}") for i in range(30)}
    assert expiry.sweep(seen, [], {}) == []
    assert all(r["active"] for r in seen.values())

    # Below the threshold the same verdicts do close.
    few = {str(i): rec("successfactors", url=f"https://x/{i}") for i in range(5)}
    assert len(expiry.sweep(few, [], {})) == 5


def test_probe_url_parsers():
    assert expiry.WORKDAY_URL.match(
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Israel-Tel-Aviv/Senior-Data-Center-Engineer_JR2023708"
    ).groups() == ("nvidia", "wd5", "NVIDIAExternalCareerSite", "Israel-Tel-Aviv/Senior-Data-Center-Engineer_JR2023708")
    assert expiry.INDEED_KEY.search("https://www.indeed.com/viewjob?jk=d4bebf725b1a1a74").group(1) == "d4bebf725b1a1a74"
    assert expiry._workday_alive("https://example.com/not-workday") is None
    assert expiry._smartrecruiters_alive("https://example.com/x") is None
    assert expiry._jibe_alive("https://example.com/x") is None


# --- SuccessFactors: removed postings that still answer 200 -------------

class _SFResp:
    def __init__(self, text, url, status=200):
        self.text, self.url, self.status_code = text, url, status


SF_URL = "https://careers.pge.com/job/Oakland-Principal-Electric-Program-Manager-CA-94612/1434989200/"
SF_TITLE = "Principal Electric Program Manager"
SF_SHELL = (f"<html><head><title>{SF_TITLE} Job Details | "
            "Pacific Gas And Electric Company</title></head><body>"
            "<nav>Search All Jobs</nav></body></html>")
# PG&E's live pages carry the title field; NextEra's carry only the posting block.
SF_LIVE_PGE = SF_SHELL.replace("<nav>", '<span data-careersite-propertyid="title">x</span><nav>')
SF_LIVE_NEXTERA = SF_SHELL.replace(
    "<nav>", '<div itemprop="description">Requisition ID # 1. Lead gas development.</div><nav>')


def _search_page(*ids):
    return "".join(f'<a class="jobTitle-link" href="/job/Oakland-Role/{i}/">Role</a>' for i in ids)


def _fake_site(page, results):
    """requests.get stand-in: the posting URL serves `page`; the search
    serves `results`, a list of pages (lists of requisition ids) in request
    order (the last repeating, as the real search does), or an int status
    for a failing search."""
    calls = []

    def get(url, params=None, **kw):
        if "/search/" not in url:
            text, status = page if isinstance(page, tuple) else (page, 200)
            return _SFResp(text, url if "errorpage" not in text else url + "errorpage/", status)
        if isinstance(results, int):
            return _SFResp("", url, results)
        n = len(calls)
        calls.append(params["startrow"])
        return _SFResp(_search_page(*(results[n] if n < len(results) else results[-1])), url)
    return get


@pytest.mark.parametrize("page,results,want", [
    (SF_LIVE_PGE, [], True),
    (SF_LIVE_NEXTERA, [], True),                     # no title field: the block decides
    (SF_SHELL, [["1400000001"], ["1400000002"]], False),             # shell, gone from search (2026-10-02)
    (SF_SHELL, [["1400000001"], ["1434989200"]], True),         # shell, but listed on page 2: a bad load
    (SF_SHELL, 503, None),                             # search unreadable
    (SF_SHELL, [[]], None),                            # search returned no job links at all
    (("<title>x</title>", 503), [], None),
    ("<title>Access denied</title>", [], None),        # not the site's job shell
])
def test_successfactors_probe(monkeypatch, page, results, want):
    monkeypatch.setattr(expiry.requests, "get", _fake_site(page, results))
    assert expiry._successfactors_alive(SF_URL, SF_TITLE) is want


def test_successfactors_error_redirect(monkeypatch):
    monkeypatch.setattr(expiry.requests, "get", lambda url, **k: _SFResp("", url + "errorpage/"))
    assert expiry._successfactors_alive(SF_URL, SF_TITLE) is False


def test_search_that_never_ends_is_unknown(monkeypatch):
    pages = [[str(1400000000 + n)] for n in range(100)]               # always a fresh page
    monkeypatch.setattr(expiry.requests, "get", _fake_site(SF_SHELL, pages))
    assert expiry._successfactors_alive(SF_URL, SF_TITLE) is None

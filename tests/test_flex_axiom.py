"""Model-free tests for the close watch on Flex and its Axiom spin-off
(owner, 2026-11-06): every posting under Workday facet sets, and EPC
Power's Paylocity board.

Run: python -m pytest -q tests
"""
import pytest

from src import expiry, state
from src.models import Job
from src.sources import career_sites, workday


class _Resp:
    def __init__(self, data=None, text=""):
        self._data, self.text, self.status_code = data, text, 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


BOARD = {"host": "x.wd1.myworkdayjobs.com", "tenant": "x", "site": "Careers", "company": "Flex",
         "facet_sets": [{"company": "Flex (Axiom)", "facets": {"Co": ["axm"]}},
                        {"facets": {"Country": ["us"]}}]}


def test_facet_sets_page_every_posting_and_the_first_set_names_the_company(monkeypatch):
    postings = {"axm": [f"/job/A_{i}" for i in range(3)],
                "us": ["/job/A_0"] + [f"/job/U_{i}" for i in range(44)]}
    calls = []

    def post(url, json, **kw):
        key = next(iter(json["appliedFacets"].values()))[0]
        calls.append((key, json["offset"]))
        rows = postings[key][json["offset"]:json["offset"] + json["limit"]]
        total = len(postings[key]) if json["offset"] == 0 else 0  # Workday: first page only
        return _Resp({"total": total, "jobPostings": [
            {"title": p, "externalPath": p, "locationsText": "USA, TX, Austin"} for p in rows]})

    monkeypatch.setattr(workday.requests, "post", post)
    monkeypatch.setattr(workday.time, "sleep", lambda s: None)
    jobs = workday.fetch_board(BOARD, ["ignored"])
    assert len(jobs) == 47, "3 Axiom + 44 more US, the shared one once"
    assert {j.company for j in jobs if "A_" in j.title} == {"Flex (Axiom)"}
    assert [o for k, o in calls if k == "us"] == [0, 20, 40]


PAGE = """<script>window.pageData = {"Jobs":[
 {"JobId":1,"JobTitle":"Product Manager","PublishedDate":"2026-05-05T10:00:00-06:00",
  "Description":"Owns the PCS roadmap. $150,000 - $180,000 per year","IsInternal":false,
  "JobLocation":{"City":"Poway","State":"CA"},"IsRemote":false},
 {"JobId":2,"JobTitle":"Senior Director of Sales","PublishedDate":"2026-11-02T10:00:00-06:00",
  "Description":"","IsInternal":false,"JobLocation":{"City":null,"State":null},"IsRemote":true},
 {"JobId":3,"JobTitle":"Internal only","IsInternal":true,"JobLocation":{}},
 {"JobId":4,"JobTitle":null,"IsInternal":false,"JobLocation":{}}
]};</script>"""


def test_paylocity_reads_the_board_pages_json(monkeypatch):
    monkeypatch.setattr(career_sites.requests, "get", lambda url, **kw: _Resp(text=PAGE))
    jobs = career_sites.fetch_paylocity({"company": "EPC Power", "guid": "g"}, [])
    assert [(j.title, j.location, j.work_mode, j.date_posted) for j in jobs] == [
        ("Product Manager", "Poway, CA", "", "2026-05-05"),
        ("Senior Director of Sales", "Remote", "remote", "2026-11-02")]
    assert jobs[0].url.endswith("/Recruiting/Jobs/Details/1") and jobs[0].pay
    assert "paylocity" in expiry.ATS_PROVIDERS, "a full list: closures by snapshot"



def test_a_unit_posting_matches_the_one_stored_as_flex():
    url = "https://flextronics.wd1.myworkdayjobs.com/en-US/Careers/job/Dallas/EE-Manager_WD214999-1"
    seen: dict = {}
    state.split_new([Job("Electrical Engineering Manager", "Flex", "USA, TX, Dallas", url, "workday")], seen)
    unit = Job("Electrical Engineering Manager", "Flex (Crown Technical Systems)",
               "USA, TX, Dallas", url, "workday")
    assert state.split_new([unit], seen) == [] and len(seen) == 1


def test_a_stale_facet_skips_its_set_but_not_the_board(monkeypatch):
    def post(url, json, **kw):
        if "Co" in json["appliedFacets"]:
            raise RuntimeError("400 Bad Request")
        return _Resp({"total": 1, "jobPostings": [
            {"title": "PM", "externalPath": "/job/U_1", "locationsText": "USA"}]})
    monkeypatch.setattr(workday.requests, "post", post)
    assert [j.title for j in workday.fetch_board(BOARD, [])] == ["PM"]
    monkeypatch.setattr(workday.requests, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        workday.fetch_board(BOARD, [])


def test_paylocity_without_a_jobs_list_fails_rather_than_closing_everything(monkeypatch):
    page = "<script>window.pageData = {\"Departments\":[]};</script>"
    monkeypatch.setattr(career_sites.requests, "get", lambda url, **kw: _Resp(text=page))
    with pytest.raises(ValueError):
        career_sites.fetch_paylocity({"company": "EPC Power", "guid": "g"}, [])

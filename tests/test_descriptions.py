"""Model-free tests for fetching descriptions of tracked postings that the
day's fetch did not return (used by the one-time re-score).

Run: python -m pytest -q tests
"""
import pytest

from src import descriptions, expiry


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(descriptions.time, "sleep", lambda s: None)
    monkeypatch.setattr(expiry, "indeed_headers", lambda: {"indeed-api-key": "k"})


def test_indeed_batch_skips_expired_and_unknown(monkeypatch):
    def post(url, json=None, **kw):
        assert sorted(json["variables"]["keys"]) == ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"]
        return _Resp(200, {"data": {"jobData": {"results": [
            {"job": {"key": "aaaaaaaaaaaaaaaa", "expired": False, "description": {"html": "<p>Own the <b>BESS</b> roadmap</p>"}}},
            {"job": {"key": "bbbbbbbbbbbbbbbb", "expired": True, "description": {"html": "<p>gone</p>"}}},
            None]}}})
    monkeypatch.setattr(descriptions.requests, "post", post)
    recs = {k: {"source": "indeed", "url": f"https://www.indeed.com/viewjob?jk={k * 16}"} for k in "abc"}
    assert descriptions.fetch(recs) == {"a": "Own the BESS roadmap"}


def test_workday_reads_the_job_endpoint(monkeypatch):
    def get(url, **kw):
        assert url == "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Careers/job/US-Remote/PM_R1"
        return _Resp(200, {"jobPostingInfo": {"jobDescription": "<ul><li>Lead PCS</li></ul>"}})
    monkeypatch.setattr(descriptions.requests, "get", get)
    recs = {"w": {"source": "workday", "url": "https://acme.wd1.myworkdayjobs.com/en-US/Careers/job/US-Remote/PM_R1"},
            "x": {"source": "greenhouse", "url": "https://boards.greenhouse.io/x/jobs/1"}}
    assert descriptions.fetch(recs) == {"w": "Lead PCS"}


def test_failures_return_nothing(monkeypatch):
    monkeypatch.setattr(descriptions.requests, "get", lambda url, **kw: _Resp(403, {"errorCode": "S22"}))
    monkeypatch.setattr(descriptions.requests, "post", lambda url, **kw: _Resp(500, {}))
    recs = {"w": {"source": "workday", "url": "https://acme.wd1.myworkdayjobs.com/en-US/Careers/job/US/PM_R1"},
            "i": {"source": "indeed", "url": "https://www.indeed.com/viewjob?jk=dddddddddddddddd"}}
    assert descriptions.fetch(recs) == {}

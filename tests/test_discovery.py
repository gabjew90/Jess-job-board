"""Model-free tests for board-identity evidence.

Run: python -m pytest -q tests
"""
import json

import pytest

from src import discovery


# --- board identity ---------------------------------------------------

class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload or {}, text

    def json(self):
        return self._p


def test_stated_name_settles_identity_both_ways(monkeypatch):
    """Greenhouse says whose board it is; that outranks any title match."""
    monkeypatch.setattr(discovery, "board_name", lambda p, s: "Energy CX")
    assert discovery.identifies("greenhouse", "energycx", "Energy CX", [], [])

    # A board full of matching titles is still rejected when the name is
    # someone else's — the "hive" / "galaxy" collision the module warns of.
    monkeypatch.setattr(discovery, "board_name", lambda p, s: "Hive Systems")
    titles = ["Director, Power Infrastructure", "BESS Engineer"]
    assert not discovery.identifies("greenhouse", "hive", "HIVE Digital", titles, titles)


@pytest.mark.parametrize("stated,company,same", [
    # Real names the five auto-discovered boards state, including the one
    # written differently by the aggregator that first surfaced it.
    ("Energy CX", "Energy CX", True),
    ("ON.energy", "ONENERGY", True),
    ("VEIR", "VEIR", True),
    ("Form Energy, Inc.", "Form Energy", True),
    ("Bitdeer", "Bitdeer Technologies Group", True),
    # The collisions the module exists to prevent. util.company_key calls
    # each of these pairs equal, which is why identity cannot use it.
    ("Hive Systems", "HIVE Digital", False),
    ("Galaxy Security", "Galaxy Digital", False),
    ("Acme Storage", "Acme Robotics", False),
    ("", "Acme", False),
])
def test_same_org_compares_whole_names(stated, company, same):
    assert discovery.same_org(stated, company) is same


def test_company_key_would_confuse_these_pairs():
    """Guards the reason same_org exists: if company_key ever became strict
    enough for identity, this test says so and same_org can be revisited."""
    from src.util import company_key
    assert company_key("Hive Systems") == company_key("HIVE Digital")


def test_generic_title_overlap_is_not_identity(monkeypatch):
    """The review's case: 'Senior Product Manager' at an unrelated company."""
    monkeypatch.setattr(discovery, "board_name", lambda p, s: None)  # ashby/lever
    assert not discovery.identifies("ashby", "acme", "Acme Storage",
                                    ["Senior Product Manager", "Office Manager"],
                                    ["Product Manager"])


def test_two_distinct_distinctive_titles_identify_a_nameless_board(monkeypatch):
    monkeypatch.setattr(discovery, "board_name", lambda p, s: None)
    known = ["Director, Power Infrastructure", "Senior BESS Commissioning Lead"]
    assert discovery.identifies("lever", "acme", "Acme Storage", list(known), known)

    # One match is not enough, however distinctive.
    assert not discovery.identifies("lever", "acme", "Acme Storage", known[:1], known)


def test_board_name_is_none_when_the_provider_publishes_none(monkeypatch):
    assert discovery.board_name("ashby", "crusoe") is None      # not in NAME_API
    monkeypatch.setattr(discovery.requests, "get", lambda *a, **k: FakeResp(404))
    assert discovery.board_name("greenhouse", "nope") is None
    monkeypatch.setattr(discovery.requests, "get", lambda *a, **k: FakeResp(200, {"name": "  "}))
    assert discovery.board_name("greenhouse", "blank") is None


def test_title_evidence_scores_against_the_longer_title():
    n, exact, distinctive = discovery.title_evidence(
        ["Product Manager"], ["Senior Product Manager, Grid Software"])
    assert n == 0, "a short generic board title must not subset-match a longer known one"
    n, exact, distinctive = discovery.title_evidence(
        ["Director, Power Infrastructure"], ["Director, Power Infrastructure"])
    assert (n, exact, distinctive) == (1, True, True)

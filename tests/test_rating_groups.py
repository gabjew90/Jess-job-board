"""Model-free tests for the rating-grouped board and digest (owner,
2026-10-02: the star and the flat list made ratings look like they did
nothing).

Run: python -m pytest -q tests
"""
import json
import re

import pytest

from src import dashboard, notify
from src.models import Job


def rec(title, band, posted="2026-10-01", **kw):
    score = dashboard.BAND_SCORE[band] if band else None
    return {"title": title, "company": "Acme", "location": "Denver, CO",
            "url": f"https://jobs.lever.co/acme/{title}", "source": "lever",
            "band": band, "score": score, "date_posted": posted,
            "first_seen": posted, "active": True, "priority": True, **kw}


def test_digest_groups_by_rating_newest_first():
    body = notify.build_digest([
        rec("Old Top", "top", "2026-09-20"), rec("New Top", "top", "2026-10-01"),
        rec("A Strong", "strong"), rec("A Possible", "possible", pay="$150k"),
        rec("A Weak", "weak"),
    ], health_summary=[], theme="gas")
    top, strong, possible = (body.index("## 🔥 Top fits"), body.index("## 🌸 Strong fits"),
                             body.index("## 💨 Possible fits"))
    assert top < strong < possible
    assert body.index("New Top") < body.index("Old Top") < strong
    # Possible roles get one line each, not a table row with a rationale.
    assert "- [A Possible](https://jobs.lever.co/acme/A Possible) · Acme" in body
    assert "A Weak" not in body and "1 lower-rated posting not listed" in body
    assert "score" not in body.lower()
    assert "🔥 **2** top · 🌸 **1** strong · 💨 **1** possible" in body
    assert "⭐" not in body


def test_digest_lists_unrated_postings():
    body = notify.build_digest([rec("Pending", None)], health_summary=[])
    assert "⏳ **1** not yet rated" in body and "## ⏳ Not yet rated" in body


def test_digest_caps_long_lower_lists():
    many = [rec(f"P{i}", "possible") for i in range(notify.POSSIBLE_CAP + 3)]
    body = notify.build_digest(many, health_summary=[])
    assert "…and 3 more on the board" in body


def test_board_rows_carry_rating_not_star(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "OUT", tmp_path / "index.html")
    mine = rec("Moved", "top", scoring_fingerprint={"owner": "2026-10-01"})
    dashboard.generate({"1": rec("Plain", "strong"), "2": mine}, [], theme="gas",
                       title="Jess")
    page = (tmp_path / "index.html").read_text()
    assert "⭐" not in page and 'class="priority"' not in page
    assert page.count("✓ your rating") == 1
    groups = json.loads(page.split("const GROUPS = ", 1)[1].split(";", 1)[0])
    assert groups["top"] == "🔥 Top fits" and groups["misfit"] == "· Misfits"
    assert "show weak &amp; misfit" in page
    assert (tmp_path / "banner.svg").exists()


def test_rating_headings_cover_every_band():
    from src import triage
    assert set(dashboard.GROUP_NAMES) == set(triage.BAND_SCORE) == set(dashboard.BAND_SCORE)


def test_gas_banner_matches_its_generator():
    import subprocess
    import sys
    from src import themes
    art = subprocess.run([sys.executable, "scripts/gas_banner.py"], check=True,
                         capture_output=True, text=True).stdout
    assert art.strip() == themes.GAS_ART.strip()


def test_phone_cards_target_named_cells(tmp_path, monkeypatch):
    """The phone layout styles cells by class; every row carries all seven
    and the heading row's cell is not one of them (it keeps its box)."""
    import re
    monkeypatch.setattr(dashboard, "OUT", tmp_path / "index.html")
    dashboard.generate({"1": rec("Role", "top")}, [], theme="battery")
    page = (tmp_path / "index.html").read_text()
    row = re.search(r"<tr[^>]* data-id=.*?</tr>", page, re.S).group(0)
    assert re.findall(r'<td class="(c-[a-z]+)"', row) == [
        "c-title", "c-co", "c-loc", "c-mode", "c-pay", "c-posted", "c-fit"]
    assert "#t td.c-title { display: contents; }" in page
    assert 'g.innerHTML = `<td colspan="7">' in page   # heading cell has no c- class


# --- the digest's title, which is also the email subject ----------------

def test_title_names_the_first_row_of_the_best_section():
    recs = [rec("Older Top", "top", "2026-09-20"),
            rec("Newest Top", "top", "2026-10-02", company="Google"),
            rec("A Strong", "strong"), rec("A Possible", "possible")]
    title = notify.digest_title(recs, [], 40, "battery")
    assert title == "⚡ Top fit: Newest Top at Google (+1 top, 1 strong)"
    body = notify.build_digest(recs, health_summary=[], theme="battery")
    top = body.split("## ⚡ Top fits", 1)[1]
    assert top.index("Newest Top") < top.index("Older Top")


def test_title_for_lower_ratings_and_edge_cases():
    assert notify.digest_title([rec("Analyst", "strong")], [{}], 40, "gas") == \
        "🌸 Strong fit: Analyst at Acme · 1 closed"
    assert notify.digest_title([rec("Ops", "possible", company=""), rec("P", None)], [], 40, "gas") == \
        "💨 Possible fit: Ops (+1 unrated)"
    assert notify.digest_title([rec("Pending", None)], [], 40) == "⏳ 1 new posting, not yet rated"
    # A legacy number just above the floor reads as weak and never headlines.
    assert notify.digest_title([{**rec("Low", None), "score": 42}], [], 40) == "Job watch: no new fits"
    assert notify.digest_title([rec("", "top"), rec("Real", "top")], [], 40) == \
        "⚡ Top fit: Real at Acme (+1 top)"
    long = notify.digest_title([rec("X" * 80, "top")], [], 40)
    assert long == "⚡ Top fit: " + "X" * 44 + "… at Acme"


def test_recent_finds_carry_the_new_badge(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    day = lambda n: (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")
    monkeypatch.setattr(dashboard, "OUT", tmp_path / "index.html")
    dashboard.generate({"1": rec("Fresh", "top", day(1)), "2": rec("Older", "top", day(2)),
                        "3": rec("Gone", "top", day(0), active=False, closed=day(0))}, [])
    page = (tmp_path / "index.html").read_text()
    classes = dict((t, c) for c, t in re.findall(
        r'<tr(?: class="([^"]*)")? data-id=[^>]*>.*?_blank">([^<]+)</a>', page, re.S))
    assert classes == {"Fresh": "new", "Older": "", "Gone": "closed"}
    assert '💵 ' in page and 'content: "NEW"' in page


def test_every_theme_defines_the_money_colours():
    from src import themes
    for th in themes.THEMES.values():
        for mode in ("light", "dark"):
            assert {"money-bg", "money-ink"} <= set(th[mode])
    assert "--money-bg:" in themes.css_vars(themes.get("gas"))


# --- work mode: arrangement phrasing only (2026-10-23) --------------------

@pytest.mark.parametrize("title,location,desc,want", [
    # The Tesla Staff PM that read remote from a product feature list.
    ("Staff Product Manager", "Palo Alto, CA",
     "black start, reactive power / Volt-VAR, anti-islanding, voltage ride-through, and remote diagnostics", ""),
    ("Engineer", "US", "Remote monitoring of remote substations.", ""),
    ("Engineer", "US", "Design hybrid inverters for hybrid solar + storage plants.", ""),
    ("Developer", "US", "Originate on-site generation and onsite power projects.", ""),
    ("Analyst", "Austin, TX", "This is a fully remote role.", "remote"),
    ("Analyst", "US", "This position can be performed remotely from anywhere in the US.", "remote"),
    ("Analyst", "US", "Remote (US) candidates welcome.", "remote"),
    ("Analyst", "US", "This is not a remote position; remote work is not offered.", ""),
    ("Manager", "Denver", "Hybrid work schedule: 3 days per week in office.", "hybrid"),
    ("Manager", "Houston", "This role is on-site in Houston.", "onsite"),
    ("Engineer (Hybrid)", "Denver", "", "hybrid"),
    ("Engineer", "Remote - Texas", "", "remote"),
    ("Engineer", "Houston, TX", "Must work 5 days per week in the office.", "onsite"),
    ("Engineer", "US", "Batteries can be remotely monitored and dispatched.", ""),
    ("Engineer", "US", "Operate fully remote-controlled substations.", ""),
    ("Remote Sensing Scientist", "Houston, TX", "", ""),
    ("Hybrid Inverter Engineer", "Austin, TX", "", ""),
    ("Analyst", "Remote", "Hybrid work schedule available at our offices.", "remote"),
    ("Analyst", "US", "This role is on-site in Houston; occasional work from home is allowed.", "onsite"),
    ("Engineer", "US", "Design hybrid (PV + BESS) plants.", ""),
    ("Engineer", "US", "Storage located onsite at customer facilities.", ""),
])
def test_work_mode_reads_arrangements_not_products(title, location, desc, want):
    from src.util import infer_work_mode
    assert infer_work_mode(title, location, desc) == want


def test_fetched_work_mode_is_recomputed_but_the_scorers_is_kept():
    from src import state
    job = Job("Staff PM", "Tesla", "Palo Alto, CA", "https://www.indeed.com/viewjob?jk=1", "indeed",
              description="voltage ride-through, and remote diagnostics")
    rec = {"title": "Staff PM", "company": "Tesla", "location": "Palo Alto, CA",
           "source": "indeed", "work_mode": "remote"}          # old misread, no provenance
    seen = {job.job_id: rec}
    state.split_new([job], seen)
    assert rec["work_mode"] == "" and rec["work_mode_by"] == ""

    # A legacy mode the old bare-word rules can't explain came from the scorer.
    rec.update(work_mode="hybrid"); rec.pop("work_mode_by")
    state.split_new([job], seen)
    assert (rec["work_mode"], rec["work_mode_by"]) == ("hybrid", "triage")

    # A tag reading holds until the source itself finds a mode.
    rec.update(work_mode="hybrid", work_mode_by="tag")
    state.split_new([job], seen)
    assert rec["work_mode"] == "hybrid"
    state.split_new([Job("Staff PM", "Tesla", "Palo Alto, CA", job.url, "indeed",
                         description="This role is on-site in Palo Alto.", work_mode="onsite")], seen)
    assert (rec["work_mode"], rec["work_mode_by"]) == ("onsite", "fetch")

    # Another source's copy never rewrites it.
    state.split_new([Job("Staff PM", "Tesla", "Palo Alto, CA", "https://x/1", "greenhouse",
                         work_mode="remote")], seen)
    assert rec["work_mode"] == "onsite"


@pytest.mark.parametrize("desc", [
    "This role is hybrid, with regular in-office presence in San Diego, CA.",
    "Hybrid Mobility Classification – Work will be performed in office 3 days.",
    "Work location: Hybrid",
])
def test_hybrid_phrasings(desc):
    from src.util import infer_work_mode
    assert infer_work_mode("Manager", "Denver, CO", desc) == "hybrid"


# --- card details: places, merged postings, reason line, one date -------

def test_url_place_and_place_dedupe():
    assert dashboard._url_place("https://x.wd1.myworkdayjobs.com/en-US/S/job/Columbus-OH/PM_R1") == "Columbus, OH"
    wd = "https://x.wd5.myworkdayjobs.com/en-US/S/job/"
    assert dashboard._url_place(wd + "USA-TX-Austin/PM_R1") == "Austin, TX"
    assert dashboard._url_place(wd + "Remote---North-Carolina-United-States/PM_R1") == "Remote, North Carolina United States"
    assert dashboard._url_place(wd + "Denver-CO-80205/PM_R1") == "Denver, CO"
    assert dashboard._url_place("https://careers.pge.com/job/Auburn-Design-Engineer-CA-95602/1431975700/") == ""
    assert dashboard._places({"location": "Oak Brook, IL, US", "locations": ["Oak Brook, IL, US", "3 Locations"]}) == \
        ["Oak Brook, IL, US", "", ""]
    assert dashboard._places({"location": "3 Locations", "url": "https://www.indeed.com/viewjob?jk=1"}) == []
    assert dashboard._places({"location": "Juno Beach, FL, US, 33408"}) == ["Juno Beach, FL, US"]
    assert dashboard._location_cell({"location": "3 Locations", "url": "https://www.indeed.com/viewjob?jk=1"},
                                    lambda s: s) == '<td class="c-loc">3 Locations</td>'
    r = {"location": "Charleston, WV, US", "locations": ["Charleston, WV, US", "Charleston, WV", "Columbus, OH"]}
    assert dashboard._places(r) == ["Charleston, WV, US", "Columbus, OH"]
    w = {"location": "3 Locations", "locations": ["3 Locations"],
         "url": "https://x.wd1.myworkdayjobs.com/en-US/S/job/Tulsa-OK/PM_R2"}
    assert dashboard._places(w) == ["Tulsa, OK", "", ""]
    cell = dashboard._location_cell(w, lambda s: s)
    assert "Tulsa, OK <small>+2</small>" in cell


def test_similar_postings_merge_into_one_card():
    a = {**rec("Project Manager (Staff) | NEW GENERATION (PSO)", "strong", "2026-10-20", company="AEP"),
         "location": "Tulsa, OK", "_id": "a"}
    b = {**rec("Project Manager (Staff) | NEW GENERATION (Kentucky Power)", "top", "2026-10-22", company="AEP"),
         "location": "Louisa, KY", "_id": "b"}
    c = {**rec("Project Manager | TRANSMISSION", "top", company="AEP"), "_id": "c"}
    shut = {**rec("Project Manager (Staff) | NEW GENERATION (Ohio)", "top", company="AEP"),
            "_id": "d", "active": False}
    other = {**rec("Project Manager (Staff) | NEW GENERATION (PSO)", "top", company="AEP Wire Co"), "_id": "e"}
    out = dashboard._merge_similar([a, b, c, shut, other])
    assert [r["_id"] for r in out] == ["b", "c", "d", "e"], \
        "best-rated copy leads; other titles, closed rows and other companies stay"
    assert out[0]["_ids"] == ["b", "a"]
    row = dashboard._row(out[0])
    assert 'data-ids="b a"' in row and 'data-places="Louisa, KY; Tulsa, OK"' in row
    assert out[0]["_similar"] == 2 and out[0]["_places"] == ["Louisa, KY", "Tulsa, OK"]
    assert "2 postings" in dashboard._location_cell(out[0], lambda s: s)


def test_row_shows_reason_one_date_and_no_source():
    r = {**rec("Role", "top", "2026-10-20"), "source": "indeed", "rationale": "x " * 200, "_id": "r"}
    row = dashboard._row(r)
    assert '<small class="why">' in row and "…" in row and "indeed" not in row
    assert 'data-d="2026-10-20" data-k="posted"' in row
    r2 = {**r, "date_posted": "", "first_seen": "2026-10-25"}
    assert 'data-d="2026-10-25" data-k="seen"' in dashboard._row(r2)


def test_reason_drops_the_owner_verdict_prefix():
    r = {"rationale": "Owner feedback (#67): Great fit, belongs higher. Owner feedback (#9): x. Senior TPM owning power."}
    assert dashboard._reason(r) == "Senior TPM owning power."


def test_digest_closed_lines_say_how_long_not_a_score():
    gone = {**rec("Old Role", "strong", "2026-09-01"), "first_seen": "2026-09-01", "closed": "2026-10-13",
            "active": False, "score": 75}
    body = notify.build_digest([], health_summary=[], closed_recs=[gone], theme="gas")
    assert "~~Old Role~~ · Acme (strong, listed 6 weeks)" in body and "75" not in body


def test_listed_for_uses_earliest_start_and_months():
    from src.notify import _listed_for
    assert _listed_for({"first_seen": "2026-10-20", "date_posted": "2026-09-01",
                        "closed": "2026-10-23"}) == "listed 7 weeks"
    assert _listed_for({"first_seen": "2026-04-01", "closed": "2026-10-01"}) == "listed 6 months"
    assert _listed_for({"first_seen": "2026-10-05", "closed": "2026-10-01"}) == ""


def test_archive_check_has_no_score_or_owner_prefix():
    from src.notify import build_digest
    body = build_digest([], health_summary=[], audit_recs=[
        {"title": "Old", "company": "C", "score": 20, "url": "https://x/1",
         "rationale": "Owner feedback (#67): Bad fit, belongs lower. Sells meters."}])
    assert "20" not in body.split("archived roles")[1] and "Owner feedback" not in body

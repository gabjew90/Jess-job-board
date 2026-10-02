"""Model-free tests for the rating-grouped board and digest (owner,
2026-10-02: the star and the flat list made ratings look like they did
nothing).

Run: python -m pytest -q tests
"""
import json

from src import dashboard, notify


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
    assert "A Weak" not in body and "1 low-fit posting" in body
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

import html
import re

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}


# Employers whose sources disagree on their own name. Without these, an
# acronym and a spelled-out name key differently and the same posting shows
# up twice (Indeed "Pacific Gas and Electric" vs careers site "PG&E").
# Extend as new variants appear; only ever merge names of the SAME company.
COMPANY_ALIASES = {
    "pge": ("pacific gas", "pg&e", "pge corporation"),
    "sce": ("southern california edison", "edison international"),
    "sdge": ("san diego gas", "sdg&e"),
    "sempra": ("sempra",),
    "google": ("alphabet", "google"),
    "meta": ("meta platforms", "facebook"),
    "amazon": ("amazon", "amazon web services", "aws"),
    "nextera": ("nextera", "florida power & light"),
    "gevernova": ("ge vernova", "general electric vernova"),
    "lges": ("lg energy solution", "lg chem"),
    "servicetitan": ("servicetitan", "service titan"),
    "corescientific": ("core scientific",),
    "appliednova": ("applied digital",),
    # "amd" alone would also match Amdocs; only the spelled-out form maps.
    "amd": ("advanced micro devices",),
    "flex": ("flextronics", "flex ltd"),
}


def company_key(company: str) -> str:
    """Normalize company for cross-source twin matching (Amazon.com Services
    LLC == Amazon Web Services == Amazon; PG&E == Pacific Gas and Electric)."""
    raw = (company or "").lower()
    for canonical, variants in COMPANY_ALIASES.items():
        if any(v in raw for v in variants):
            return canonical
    c = re.sub(r"[^a-z0-9 ]", "", raw.replace(".com", ""))
    c = re.sub(r"\b(inc|llc|corp|corporation|company|services|ltd|co)\b", "", c).strip()
    return c.split()[0] if c.split() else ""


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:40]


def city_key(location: str) -> str:
    """First locality token: 'Herndon, Virginia, USA' == 'Herndon, VA'."""
    return re.sub(r"[^a-z]", "", (location or "").split(",")[0].lower())


def twin_key(company: str, title: str, location: str) -> tuple:
    return (company_key(company), title_key(title), city_key(location))


def source_id(url: str) -> str:
    """The ATS's own id for a posting, from its URL.

    Titles change — an employer renamed a role and it looked like the old
    posting closed and a brand new one appeared. The ATS id is stable
    across renames, so it is the strongest identity we have.
    """
    if not url:
        return ""
    m = re.search(r"[?&](?:gh_jid|jk|jobId|id)=([A-Za-z0-9-]+)", url)
    if m:
        return m.group(1)
    # Radancy-style paths put the id BEFORE the slug: /job/<id>/<title-slug>/
    m = re.search(r"/job/(\d{4,})/", url)
    if m:
        return m.group(1)
    tail = url.rstrip("/").split("/")[-1].split("?")[0]
    # numeric id, uuid, or a requisition code like R24478-1
    if re.fullmatch(r"\d{4,}|[0-9a-f]{8}-[0-9a-f-]{20,}|[A-Z]{1,3}\d{3,}[-\w]*", tail):
        return tail
    m = re.search(r"_([A-Z]{1,3}\d{3,}[-\w]*)$", tail)
    return m.group(1) if m else ""


def group_key(company: str, title: str) -> tuple:
    """Same company + title = ONE opening, however many metros it is posted
    to. Employers and aggregators syndicate a single req city-by-city (a
    remote role appeared in 19 cities), which is the main source of visible
    duplicates. Extra locations are kept on the surviving record."""
    return (company_key(company), title_key(title))


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_pay(text: str) -> str:
    """Pull a salary range out of free text (US pay-transparency style)."""
    if not text:
        return ""
    m = re.search(
        r"(?:USD\s?)?\$\s?\d[\d,.]*\s?[kK]?\s?(?:[-–—]|to)\s?"
        r"(?:USD\s?)?\$?\s?\d[\d,.]*\s?[kK]?(?:\s?(?:per|/)\s?\w+)?",
        text)
    if not m:  # single figure, only if clearly a salary-sized amount
        m = re.search(r"\$\s?\d{2,3},\d{3}(?:\.\d+)?", text)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else ""


def infer_work_mode(title: str, location: str, description: str) -> str:
    """Best-effort onsite/hybrid/remote from text; structured fields win
    over this in the fetchers that have them."""
    strong = f"{title} {location}".lower()
    desc = (description or "").lower()
    if "hybrid" in strong or "hybrid" in desc:
        return "hybrid"
    if "remote" in strong:
        return "remote"
    if re.search(r"\b(?:fully|100%)?\s?remote\b", desc) and "not remote" not in desc:
        return "remote"
    if re.search(r"\bon-?\s?site\b", desc):
        return "onsite"
    return ""


ROLE_MARKERS = (
    "what you'll do", "what you will do", "responsibilities", "the role",
    "in this role", "about the role", "about this role", "your impact",
    "position summary", "job summary", "key duties", "what you'll bring",
    "qualifications", "requirements", "you will",
)


def role_excerpt(description: str, limit: int) -> str:
    """Excerpt the part of a posting that describes the ROLE.

    Many postings open with company boilerplate ("About X…") long enough to
    consume the whole prompt budget, starving the scorer of actual scope —
    which then reads as "scope unclear" and depresses the band. When a
    role-content marker appears after leading boilerplate, start there.
    """
    if not description or len(description) <= limit:
        return description or ""
    low = description.lower()
    starts = [low.find(m) for m in ROLE_MARKERS]
    hits = [i for i in starts if i > 150]
    if hits:
        start = max(0, min(hits) - 100)
        return description[start:start + limit]
    return description[:limit]

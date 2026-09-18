"""Common Job record all sources normalize into."""
from dataclasses import dataclass, asdict
import hashlib
import re


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    date_posted: str = ""
    pay: str = ""
    work_mode: str = ""  # onsite | hybrid | remote | ""
    priority: bool = False

    @property
    def job_id(self) -> str:
        # URL-independent so the same role found via two boards dedupes.
        key = "|".join(_norm(x) for x in (self.company, self.title, self.location))
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["job_id"] = self.job_id
        return d

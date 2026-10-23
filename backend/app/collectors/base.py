import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..config import settings


@dataclass
class RawJob:
    source: str
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    remote: bool = False
    url: str = ""
    description: str = ""
    posted_at: datetime | None = None
    salary: str = ""


class CollectorError(Exception):
    pass


class Collector:
    name = "base"
    label = "Base"

    def fetch(self, prefs: dict) -> list[RawJob]:
        raise NotImplementedError

    def enrich(self, job: RawJob) -> RawJob:  # opcional: buscar descrição completa só para vagas novas
        return job


def client():
    import httpx
    return httpx.Client(timeout=30, follow_redirects=True,
                        headers={"User-Agent": settings.USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})


def polite_sleep(mult: float = 1.0):
    time.sleep(settings.HTTP_DELAY_SECONDS * mult)


def clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = BeautifulSoup(html.unescape(raw), "html.parser").get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def from_epoch(v) -> datetime | None:
    try:
        v = float(v)
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def from_iso(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None

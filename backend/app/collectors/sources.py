"""Coletores. Preferência por APIs/feeds públicos; o do LinkedIn usa o endpoint público 'guest'
(sem login) e é frágil/limitado por natureza — veja o README sobre termos de uso."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .base import Collector, CollectorError, RawJob, clean_html, client, from_epoch, from_iso, polite_sleep


def _queries(prefs: dict) -> list[str]:
    return prefs.get("queries") or ["software engineer", "python developer"]


class Greenhouse(Collector):
    name, label = "greenhouse", "Greenhouse (boards configurados)"

    def fetch(self, prefs):
        out = []
        with client() as c:
            for board in prefs.get("greenhouse_boards", []):
                r = c.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", params={"content": "true"})
                if r.status_code != 200:
                    continue
                for j in r.json().get("jobs", []):
                    loc = (j.get("location") or {}).get("name", "")
                    out.append(RawJob("greenhouse", f"{board}:{j['id']}", j.get("title", ""), board.title(), loc,
                                      "remote" in loc.lower() or "remoto" in loc.lower(), j.get("absolute_url", ""),
                                      clean_html(j.get("content", "")), from_iso(j.get("updated_at"))))
                polite_sleep(0.3)
        return out


class Lever(Collector):
    name, label = "lever", "Lever (empresas configuradas)"

    def fetch(self, prefs):
        out = []
        with client() as c:
            for comp in prefs.get("lever_companies", []):
                r = c.get(f"https://api.lever.co/v0/postings/{comp}", params={"mode": "json"})
                if r.status_code != 200:
                    continue
                for j in r.json():
                    cat = j.get("categories") or {}
                    loc = cat.get("location", "") or ""
                    out.append(RawJob("lever", f"{comp}:{j['id']}", j.get("text", ""), comp.title(), loc,
                                      j.get("workplaceType") == "remote" or "remote" in loc.lower(), j.get("hostedUrl", ""),
                                      j.get("descriptionPlain", "") or clean_html(j.get("description", "")), from_epoch(j.get("createdAt"))))
                polite_sleep(0.3)
        return out


class Remotive(Collector):
    name, label = "remotive", "Remotive (API pública)"

    def fetch(self, prefs):
        out, seen = [], set()
        with client() as c:
            for q in _queries(prefs)[:3]:
                r = c.get("https://remotive.com/api/remote-jobs", params={"search": q, "limit": 50})
                if r.status_code != 200:
                    continue
                for j in r.json().get("jobs", []):
                    if j["id"] in seen:
                        continue
                    seen.add(j["id"])
                    out.append(RawJob("remotive", str(j["id"]), j.get("title", ""), j.get("company_name", ""),
                                      j.get("candidate_required_location", ""), True, j.get("url", ""),
                                      clean_html(j.get("description", "")), from_iso(j.get("publication_date")), j.get("salary", "")))
                polite_sleep()
        return out


class RemoteOK(Collector):
    name, label = "remoteok", "RemoteOK (API pública)"

    def fetch(self, prefs):
        with client() as c:
            r = c.get("https://remoteok.com/api")
        if r.status_code != 200:
            raise CollectorError(f"HTTP {r.status_code}")
        out = []
        for j in r.json():
            if not isinstance(j, dict) or "id" not in j:
                continue
            sal = f"{j['salary_min']}-{j['salary_max']} USD" if j.get("salary_min") else ""
            out.append(RawJob("remoteok", str(j["id"]), j.get("position", ""), j.get("company", ""), j.get("location", "") or "Remote",
                              True, j.get("url", ""), clean_html(j.get("description", "")), from_iso(j.get("date")), sal))
        return out


class Arbeitnow(Collector):
    name, label = "arbeitnow", "Arbeitnow (API pública)"

    def fetch(self, prefs):
        out = []
        with client() as c:
            for page in (1, 2):
                r = c.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
                if r.status_code != 200:
                    break
                for j in r.json().get("data", []):
                    out.append(RawJob("arbeitnow", j["slug"], j.get("title", ""), j.get("company_name", ""), j.get("location", ""),
                                      bool(j.get("remote")), j.get("url", ""), clean_html(j.get("description", "")), from_epoch(j.get("created_at"))))
                polite_sleep()
        return out


class WeWorkRemotely(Collector):
    name, label = "weworkremotely", "We Work Remotely (RSS)"
    FEEDS = ["remote-programming-jobs", "remote-full-stack-programming-jobs", "remote-back-end-programming-jobs"]

    def fetch(self, prefs):
        out = []
        with client() as c:
            for f in self.FEEDS:
                r = c.get(f"https://weworkremotely.com/categories/{f}.rss")
                if r.status_code != 200:
                    continue
                for it in ET.fromstring(r.content).iter("item"):
                    raw_title = it.findtext("title", "")
                    company, _, title = raw_title.partition(": ")
                    try:
                        posted = parsedate_to_datetime(it.findtext("pubDate", "")).replace(tzinfo=None)
                    except (TypeError, ValueError):
                        posted = None
                    out.append(RawJob("weworkremotely", it.findtext("guid", it.findtext("link", "")), title or raw_title, company,
                                      it.findtext("region", "") or "Remote", True, it.findtext("link", ""),
                                      clean_html(it.findtext("description", "")), posted))
                polite_sleep()
        return out


class Gupy(Collector):
    """Portal público da Gupy (vagas de empresas brasileiras). API não documentada: pode mudar."""
    name, label = "gupy", "Gupy (Brasil, API do portal)"

    def fetch(self, prefs):
        out, seen = [], set()
        with client() as c:
            # 1ª passada pede Belo Horizonte (se a API ignorar o filtro, a faixa de localização resolve depois); 2ª, geral
            for q, extra in [(q, e) for q in _queries(prefs)[:4] for e in ({"city": "Belo Horizonte", "state": "Minas Gerais"}, {})]:
                r = c.get("https://portal.api.gupy.io/api/job", params={"name": q, "limit": 50, "offset": 0, **extra})
                if r.status_code != 200:
                    continue
                for j in r.json().get("data", []):
                    if j["id"] in seen:
                        continue
                    seen.add(j["id"])
                    loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
                    out.append(RawJob("gupy", str(j["id"]), j.get("name", ""), j.get("careerPageName", ""), loc,
                                      bool(j.get("isRemoteWork")), j.get("jobUrl", ""), clean_html(j.get("description", "")),
                                      from_iso(j.get("publishedDate"))))
                polite_sleep()
        return out


def parse_linkedin_cards(html_text: str) -> list[RawJob]:
    soup = BeautifulSoup(html_text, "html.parser")
    out, seen = [], set()
    for card in soup.select("li, div.base-card"):
        urn = card.get("data-entity-urn") or (card.select_one("[data-entity-urn]") or {}).get("data-entity-urn", "")
        m = re.search(r"(\d{6,})", urn or "")
        title_el = card.select_one(".base-search-card__title")
        if not m or not title_el or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        link = card.select_one("a.base-card__full-link")
        t = card.select_one("time")
        loc = (card.select_one(".job-search-card__location") or title_el).get_text(strip=True) if card.select_one(".job-search-card__location") else ""
        out.append(RawJob("linkedin", m.group(1), title_el.get_text(strip=True),
                          (card.select_one(".base-search-card__subtitle") or title_el).get_text(strip=True) if card.select_one(".base-search-card__subtitle") else "",
                          loc, "remote" in loc.lower() or "remoto" in loc.lower(),
                          (link["href"].split("?")[0] if link else f"https://www.linkedin.com/jobs/view/{m.group(1)}"),
                          "", from_iso(t.get("datetime") + "T00:00:00") if t and t.get("datetime") else None))
    return out


class LinkedInGuest(Collector):
    """Busca pública de vagas do LinkedIn SEM login. Limitado a poucas páginas, com pausas.
    Não use sua conta: scraping logado viola os termos do LinkedIn e pode banir o perfil."""
    name, label = "linkedin", "LinkedIn (busca pública, sem login)"
    SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobs/search"
    DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"

    def fetch(self, prefs):
        days = int(prefs.get("max_age_days", 14))
        out, seen = [], set()
        with client() as c:
            for q in _queries(prefs)[:4]:
                for li, loc in enumerate(prefs.get("linkedin_locations", ["Brazil"])[:3]):
                    # o 1º local (Belo Horizonte) recebe 3 páginas; os demais, só a mais recente
                    for start in ((0, 25, 50) if li == 0 else (0,)):
                        url = f"{self.SEARCH}?keywords={quote_plus(q)}&location={quote_plus(loc)}&f_TPR=r{days * 86400}&start={start}"
                        r = c.get(url)
                        if r.status_code in (429, 999):
                            raise CollectorError(f"LinkedIn limitou as requisições (HTTP {r.status_code}); tente mais tarde")
                        if r.status_code != 200:
                            break
                        cards = parse_linkedin_cards(r.text)
                        for j in cards:
                            if j.external_id not in seen:
                                seen.add(j.external_id)
                                out.append(j)
                        if len(cards) < 20:
                            break
                        polite_sleep(1.5)
                    polite_sleep(1.5)
        return out

    def enrich(self, job: RawJob) -> RawJob:
        with client() as c:
            r = c.get(self.DETAIL.format(id=job.external_id))
        if r.status_code == 200:
            el = BeautifulSoup(r.text, "html.parser").select_one(".show-more-less-html__markup")
            job.description = el.get_text("\n", strip=True) if el else ""
        polite_sleep(1.5)
        return job


REGISTRY = {c.name: c for c in (Greenhouse(), Lever(), Remotive(), RemoteOK(), Arbeitnow(), WeWorkRemotely(), Gupy(), LinkedInGuest())}

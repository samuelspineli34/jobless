"""Coletores aprimorados para extração massiva de vagas (incluindo LinkedIn, Gupy, Greenhouse, Lever, etc.)."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .base import Collector, CollectorError, RawJob, clean_html, client, from_epoch, from_iso, polite_sleep


def _queries(prefs: dict) -> list[str]:
    return prefs.get("queries") or [
        "software engineer", "python developer", "backend developer", 
        "desenvolvedor python", "desenvolvedor backend", "engenheiro de software",
        "programador", "desenvolvedor"
    ]


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
            for q in _queries(prefs)[:4]:
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


class Himalayas(Collector):
    name, label = "himalayas", "Himalayas (API pública)"

    def fetch(self, prefs):
        out = []
        with client() as c:
            for offset in (0, 20, 40):
                r = c.get("https://himalayas.app/jobs/api", params={"limit": 20, "offset": offset}, timeout=20)
                if r.status_code != 200:
                    if offset == 0:
                        raise CollectorError(f"Himalayas HTTP {r.status_code}")
                    break
                payload = r.json()
                rows = payload.get("jobs", []) if isinstance(payload, dict) else []
                if not rows:
                    break
                for j in rows:
                    title = j.get("title") or ""
                    company = j.get("companyName") or j.get("company_name") or j.get("company") or ""
                    url = j.get("applicationLink") or j.get("url") or j.get("application_url") or ""
                    ext = str(j.get("guid") or j.get("id") or url)
                    if not title or not url or not ext:
                        continue
                    loc = j.get("location") or j.get("locationRestrictions") or "Remote"
                    if isinstance(loc, list):
                        loc = ", ".join(map(str, loc))
                    desc = j.get("description") or j.get("excerpt") or ""
                    posted = from_iso(j.get("pubDate") or j.get("publishedAt") or j.get("createdAt"))
                    out.append(RawJob("himalayas", ext, title, company, str(loc), True, url, clean_html(desc), posted,
                                      str(j.get("salary") or "")))
                polite_sleep(0.5)
        return out


class Jobicy(Collector):
    name, label = "jobicy", "Jobicy (API pública)"

    def fetch(self, prefs):
        out, seen = [], set()
        with client() as c:
            for tag in ("software-development", "javascript", "python"):
                r = c.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": tag}, timeout=20)
                if r.status_code != 200:
                    continue
                payload = r.json()
                for j in payload.get("jobs", []) if isinstance(payload, dict) else []:
                    url = j.get("url") or ""
                    ext = str(j.get("id") or url)
                    if not ext or ext in seen:
                        continue
                    seen.add(ext)
                    title = j.get("jobTitle") or j.get("title") or ""
                    if not title or not url:
                        continue
                    loc = j.get("jobGeo") or j.get("jobIndustry") or "Remote"
                    out.append(RawJob("jobicy", ext, title, j.get("companyName") or "", str(loc), True, url,
                                      clean_html(j.get("jobDescription") or j.get("description") or ""),
                                      from_iso(j.get("pubDate") or j.get("publishedAt")), str(j.get("annualSalary") or "")))
                polite_sleep(0.5)
        return out

class Gupy(Collector):
    name, label = "gupy", "Gupy (Belo Horizonte, MG e Brasil)"

    def fetch(self, prefs):
        out, seen = [], set()
        # Termos focados em tecnologia e desenvolvimento
        queries = [
            "desenvolvedor", "programador", "software engineer", 
            "python", "backend", "full stack", "analista de sistemas", "engenheiro de software"
        ]
        
        # Variações geográficas amplas para capturar BH e região metropolitana
        locations_filter = [
            {"city": "Belo Horizonte", "state": "Minas Gerais"},
            {"state": "Minas Gerais"},
            {"city": "Contagem", "state": "Minas Gerais"},
            {"city": "Nova Lima", "state": "Minas Gerais"},
            {} # Geral Brasil caso o filtro restrito retorne pouco
        ]

        with client() as c:
            for q in queries:
                for loc_params in locations_filter:
                    try:
                        r = c.get("https://portal.api.gupy.io/api/job", params={"name": q, "limit": 50, "offset": 0, **loc_params}, timeout=10)
                        if r.status_code != 200:
                            continue
                        data = r.json().get("data", [])
                        for j in data:
                            job_id = str(j.get("id"))
                            if job_id in seen:
                                continue
                            seen.add(job_id)
                            
                            city = j.get("city") or ""
                            state = j.get("state") or ""
                            loc = ", ".join(x for x in (city, state, j.get("country")) if x) or "Brasil"
                            
                            out.append(RawJob(
                                source="gupy",
                                external_id=job_id,
                                title=j.get("name", ""),
                                company=j.get("careerPageName", ""),
                                location=loc,
                                remote=bool(j.get("isRemoteWork")),
                                url=j.get("jobUrl", ""),
                                description=clean_html(j.get("description", "")),
                                posted_at=from_iso(j.get("publishedDate"))
                            ))
                    except Exception:
                        pass
                    polite_sleep(0.3)
        return out

def parse_linkedin_cards(html_text: str) -> list[RawJob]:
    """Parser tolerante às variações do HTML público de vagas do LinkedIn."""
    soup = BeautifulSoup(html_text or "", "html.parser")
    out, seen = [], set()
    cards = soup.select(
        "div.base-card, li.jobs-search-results__list-item, "
        "div.job-search-card, li[data-occludable-job-id], div.job-card-container"
    )
    if not cards:
        cards = soup.select("li:has(.base-search-card__title), div:has(> .base-search-card__title)")
    for card in cards:
        title_el = card.select_one(
            ".base-search-card__title, .job-card-list__title, "
            ".job-card-container__link, h3, [class*='job-title']"
        )
        link = card.select_one(
            "a.base-card__full-link, a[href*='/jobs/view/'], "
            "a.job-card-list__title, a[href*='/jobs/']"
        )
        if not title_el and link:
            title_el = link
        if not title_el:
            continue
        title_text = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True))
        if not title_text or title_text.lower() in {"linkedin", "see more"}:
            continue
        href = (link.get("href", "") if link else "").split("?")[0]
        match_href = re.search(r"/jobs/view/(\d+)", href)
        urn = card.get("data-entity-urn") or card.get("data-occludable-job-id") or ""
        if not urn:
            urn_el = card.select_one("[data-entity-urn], [data-job-id]")
            urn = (urn_el.get("data-entity-urn") or urn_el.get("data-job-id") or "") if urn_el else ""
        match_urn = re.search(r"(\d{6,})", str(urn))
        job_id = (match_href.group(1) if match_href else match_urn.group(1) if match_urn else "")
        if not job_id:
            continue
        if job_id in seen:
            continue
        seen.add(job_id)
        if not href:
            href = f"https://www.linkedin.com/jobs/view/{job_id}/"
        elif href.startswith("/"):
            href = "https://www.linkedin.com" + href
        loc_el = card.select_one(
            ".job-search-card__location, .job-card-container__metadata-item, "
            "[class*='location'], [class*='metadata']"
        )
        comp_el = card.select_one(
            ".base-search-card__subtitle, .job-card-container__company-name, "
            "[class*='company-name'], h4"
        )
        time_el = card.select_one("time")
        loc = re.sub(r"\s+", " ", loc_el.get_text(" ", strip=True)) if loc_el else ""
        comp = re.sub(r"\s+", " ", comp_el.get_text(" ", strip=True)) if comp_el else ""
        posted = None
        if time_el:
            posted = from_iso(time_el.get("datetime"))
        out.append(RawJob(
            "linkedin", job_id, title_text, comp, loc,
            bool(re.search(r"remote|remoto|home office|work from home", loc, re.I)),
            href, "", posted
        ))
    return out


class LinkedInGuest(Collector):
    name, label = "linkedin", "LinkedIn (Busca Pública Ampliada)"
    SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobs/search"
    DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"

    def fetch(self, prefs):
        days = int(prefs.get("max_age_days", 30))
        out, seen = [], set()
        queries = _queries(prefs)[:6]
        locations = prefs.get("linkedin_locations", ["Belo Horizonte, Minas Gerais, Brazil", "Brazil", "Remote"])[:3]

        with client() as c:
            for q in queries:
                for loc in locations:
                    for start in (0, 25):
                        url = f"{self.SEARCH}?keywords={quote_plus(q)}&location={quote_plus(loc)}&f_TPR=r{days * 86400}&start={start}"
                        try:
                            r = c.get(url, timeout=15)
                            if r.status_code in (429, 999):
                                break
                            if r.status_code != 200:
                                break
                            cards = parse_linkedin_cards(r.text)
                            if not cards:
                                break
                            for j in cards:
                                if j.external_id not in seen:
                                    seen.add(j.external_id)
                                    out.append(j)
                        except Exception:
                            break
                        polite_sleep(1.0)
                    polite_sleep(1.0)
        return out

    def enrich(self, job: RawJob) -> RawJob:
        with client() as c:
            try:
                r = c.get(self.DETAIL.format(id=job.external_id), timeout=15)
                if r.status_code == 200:
                    el = BeautifulSoup(r.text, "html.parser").select_one(".show-more-less-html__markup, .description__text")
                    if el:
                        job.description = el.get_text("\n", strip=True)
            except Exception:
                pass
        polite_sleep(1.0)
        return job


REGISTRY = {c.name: c for c in (Greenhouse(), Lever(), Remotive(), RemoteOK(), Arbeitnow(), WeWorkRemotely(), Himalayas(), Jobicy(), Gupy(), LinkedInGuest())}
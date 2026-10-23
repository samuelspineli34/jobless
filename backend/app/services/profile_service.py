"""Perfil: leitura/escrita como um único documento + mesclagem de importações."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Education, Experience, Profile, Skill
from .skills import normalize_skill

DEFAULT_PREFS = {
    "prefs_version": 2,
    "focus": {"bh": 85, "brazil": 5, "remote": 10},   # % do esforço: Belo Horizonte / Brasil / remoto
    "content_language": "pt",
    "titles": ["Software Engineer", "Full-Stack Developer", "Backend Engineer", "Desenvolvedor"],
    "queries": ["software engineer", "python developer", "backend developer", "full stack developer", "desenvolvedor python"],
    "title_keywords": ["developer", "engineer", "desenvolvedor", "engenheiro", "programador", "software", "backend", "back-end",
                       "full stack", "fullstack", "full-stack", "python", "typescript"],
    "seniority": ["junior", "mid"],
    "locations": ["belo horizonte", "brazil", "brasil", "remote"],
    "accept_remote_global": True,
    "hard_location": False,
    "exclude_keywords": [],
    "blocked_companies": [],
    "max_age_days": 14,
    "min_score": 60,
    "sources": ["greenhouse", "lever", "remotive", "remoteok", "arbeitnow", "weworkremotely", "gupy", "linkedin"],
    "greenhouse_boards": ["gitlab", "cloudflare", "datadog", "stripe"],
    "lever_companies": ["spotify", "nubank"],
    "linkedin_locations": ["Belo Horizonte, Minas Gerais, Brazil", "Brazil", "Remote"],
    "weights": {"technical": 40, "experience": 25, "seniority": 15, "location": 10, "language": 10},
}


def upgraded_prefs(saved: dict | None) -> dict:
    """Mescla com os padrões; preferências salvas antes do foco por região recebem os novos padrões uma vez."""
    saved = dict(saved or {})
    if saved.get("prefs_version", 1) < 2:
        for k in ("focus", "locations", "linkedin_locations"):
            saved.pop(k, None)
        saved["prefs_version"] = 2
    return {**DEFAULT_PREFS, **saved}


def get_profile(db: Session) -> Profile:
    p = db.scalar(select(Profile).limit(1))
    if not p:
        p = Profile(preferences=dict(DEFAULT_PREFS), languages=[{"code": "pt", "level": "Nativo"}], links={}, i18n={})
        db.add(p)
        db.commit()
    return p


def profile_doc(db: Session) -> dict:
    p = get_profile(db)
    return {
        "full_name": p.full_name, "email": p.email, "phone": p.phone, "location": p.location, "headline": p.headline,
        "summary": p.summary, "links": p.links or {}, "languages": p.languages or [],
        "preferences": upgraded_prefs(p.preferences), "i18n": p.i18n or {},
        "experiences": [{"id": e.id, "company": e.company, "title": e.title, "location": e.location, "start": e.start,
                         "end": e.end, "description": e.description, "technologies": e.technologies or [],
                         "i18n": e.i18n or {}, "source": e.source}
                        for e in db.scalars(select(Experience).order_by(Experience.start.desc()))],
        "education": [{"id": e.id, "institution": e.institution, "degree": e.degree, "start": e.start, "end": e.end,
                       "i18n": e.i18n or {}} for e in db.scalars(select(Education).order_by(Education.end.desc()))],
        "skills": [{"name": s.name, "level": s.level, "years": s.years} for s in db.scalars(select(Skill).order_by(Skill.name))],
    }


def save_profile_doc(db: Session, doc: dict) -> None:
    p = get_profile(db)
    for k in ("full_name", "email", "phone", "location", "headline", "summary"):
        setattr(p, k, doc.get(k, "") or "")
    p.links, p.languages, p.i18n = doc.get("links", {}), doc.get("languages", []), doc.get("i18n", {})
    p.preferences = upgraded_prefs(doc.get("preferences", {}))
    db.query(Experience).delete()
    db.query(Education).delete()
    db.query(Skill).delete()
    for e in doc.get("experiences", []):
        db.add(Experience(company=e.get("company") or "", title=e.get("title") or "", location=e.get("location") or "",
                          start=e.get("start") or "", end=e.get("end") or None, description=e.get("description") or "",
                          technologies=e.get("technologies") or [], i18n=e.get("i18n") or {}, source=e.get("source") or "manual"))
    for e in doc.get("education", []):
        db.add(Education(institution=e.get("institution") or "", degree=e.get("degree") or "", start=e.get("start") or "",
                         end=e.get("end") or None, i18n=e.get("i18n") or {}))
    seen = set()
    for s in doc.get("skills", []):
        name = normalize_skill(s["name"])
        if name and name not in seen:
            seen.add(name)
            db.add(Skill(name=name, level=s.get("level") or "", years=s.get("years") or None))
    db.commit()


def merge_import(db: Session, parsed: dict, replace: bool = False) -> dict:
    """Mescla dados importados sem apagar o que já existe (a menos que replace=True)."""
    p = get_profile(db)
    counts = {"experiences": 0, "education": 0, "skills": 0}
    for k in ("full_name", "email", "phone", "location", "headline", "summary"):
        if parsed.get(k) and (replace or not getattr(p, k)):
            setattr(p, k, parsed[k])
    p.links = {**parsed.get("links", {}), **(p.links or {})} if not replace else {**(p.links or {}), **parsed.get("links", {})}
    langs = {x["code"]: x for x in (p.languages or [])}
    for x in parsed.get("languages", []):
        langs.setdefault(x["code"], x)
    p.languages = list(langs.values())
    if parsed.get("raw_text"):
        p.raw_text = parsed["raw_text"]
    have = {(e.company.lower(), e.title.lower(), e.start) for e in db.scalars(select(Experience))}
    for e in parsed.get("experiences", []):
        if (e["company"].lower(), e["title"].lower(), e["start"]) not in have and (e["company"] or e["title"]):
            db.add(Experience(**e))
            counts["experiences"] += 1
    have_e = {(e.institution.lower(), e.degree.lower()) for e in db.scalars(select(Education))}
    for e in parsed.get("education", []):
        if (e["institution"].lower(), e["degree"].lower()) not in have_e and e["institution"]:
            db.add(Education(**e))
            counts["education"] += 1
    have_s = {s.name for s in db.scalars(select(Skill))}
    for s in parsed.get("skills", []):
        n = normalize_skill(s)
        if n not in have_s:
            db.add(Skill(name=n))
            have_s.add(n)
            counts["skills"] += 1
    db.commit()
    return counts


def ctx_for_matching(db: Session) -> dict:
    from ..matching.scorer import total_years
    doc = profile_doc(db)
    prefs = doc["preferences"]
    return {
        "skills": {s["name"] for s in doc["skills"]}, "years": total_years(doc["experiences"]),
        "titles": list(prefs.get("titles", [])) + [e["title"] for e in doc["experiences"] if e["title"]],
        "languages": {x["code"] for x in doc["languages"]} or {"pt", "en"}, "prefs": prefs,
    }

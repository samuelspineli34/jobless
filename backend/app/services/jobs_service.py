"""Coleta -> deduplicação -> requisitos -> pontuação. Também geração de currículo para uma vaga."""
import hashlib
import re
import traceback
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collectors import REGISTRY
from ..collectors.base import RawJob
from ..config import settings
from ..matching.scorer import score_job
from ..matching.tiers import TIERS, allocate, location_tier
from ..models import Application, Experience, Job, JobMatch, JobRequirement, Resume, Education, Skill, now
from ..resumes import builder
from .profile_service import ctx_for_matching, get_profile, profile_doc
from .skills import detect_language, detect_seniority, extract_skills, split_requirements, years_required


# Termos absolutamente obrigatórios ou proibidos para bloquear lixo de outras áreas (vendas, finanças, etc.)
_FORBIDDEN_TITLES = re.compile(
    r"\b(sales|account executive|customer success|marketing|recruiter|hr manager|finance|financial|"
    r"risk|tax|legal|nurse|doctor|chef|driver|store|retail|content writer|copywriter|social media)\b", 
    re.I
)

_REQUIRED_TECH_TERMS = re.compile(
    r"\b(software|developer|engineer|desenvolvedor|engenheiro|programador|devops|sre|qa|tester|"
    r"python|javascript|typescript|java|react|node|fullstack|full-stack|backend|front-end|frontend|"
    r"architect|arquiteto|tech lead|data scientist|cientista de dados|analista de sistemas|it support|suporte ti|dev)\b",
    re.I
)


def dedupe_key(company: str, title: str, location: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()  # noqa: E731
    return hashlib.sha1(f"{norm(company)}|{norm(title)}|{norm(location.split(',')[0])}".encode()).hexdigest()


def set_requirements(db: Session, job: Job) -> None:
    job.requirements.clear()
    req_text, nice_text = split_requirements(job.description)
    req = set(extract_skills(req_text + " " + job.title))
    for s in sorted(req):
        job.requirements.append(JobRequirement(skill=s, mandatory=True))
    for s in sorted(set(extract_skills(nice_text)) - req):
        job.requirements.append(JobRequirement(skill=s, mandatory=False))


def score(db: Session, job: Job, ctx: dict | None = None) -> JobMatch:
    ctx = ctx or ctx_for_matching(db)
    r = score_job({"title": job.title, "description": job.description, "location": job.location, "remote": job.remote,
                   "language": job.language, "seniority": job.seniority, "years_required": years_required(job.description),
                   "company": job.company, "requirements": [(x.skill, x.mandatory) for x in job.requirements]}, ctx)
    m = job.match or JobMatch(job_id=job.id)
    m.score, m.eliminated, m.matched, m.gaps, m.breakdown, m.explanation, m.computed_at = (
        r["score"], r["eliminated"], r["matched"], r["gaps"], r["breakdown"], r["explanation"], now())
    job.match = m
    return m


def create_job(db: Session, raw: RawJob) -> Job:
    text = f"{raw.title}\n{raw.description}"
    job = Job(source=raw.source, external_id=raw.external_id, dedupe_key=dedupe_key(raw.company, raw.title, raw.location),
              title=raw.title[:300], company=raw.company[:200], location=raw.location[:300],
              remote=raw.remote or bool(re.search(r"\b(remote|remoto|home office|anywhere)\b", f"{raw.location} {raw.title}", re.I)),
              url=raw.url[:1000], description=raw.description, language=detect_language(text),
              salary=raw.salary[:100], seniority=detect_seniority(raw.title, raw.description), posted_at=raw.posted_at)
    db.add(job)
    db.flush()
    set_requirements(db, job)
    return job


def tier_of(job: Job) -> str:
    return location_tier(job.location, job.title, job.remote, job.language, job.description)


def run_collect(db: Session, log=print, progress=None) -> dict:
    prefs = profile_doc(db)["preferences"]
    ctx = ctx_for_matching(db)
    
    max_days = int(prefs.get("max_age_days", 30))
    cutoff = now() - timedelta(days=max_days)
    
    stats = {}
    names = [n for n in prefs.get("sources", []) if n in REGISTRY]
    for i, name in enumerate(names):
        col = REGISTRY[name]
        if progress:
            progress({"phase": "collect", "label": f"Buscando em {col.label}", "done": i, "total": len(names),
                      "new": sum(x["new"] for x in stats.values()), "sources": stats})
        st = stats[name] = {"fetched": 0, "new": 0, "duplicates": 0, "filtered": 0, "error": ""}
        try:
            raws = col.fetch(prefs)
        except Exception as e:
            st["error"] = f"{type(e).__name__}: {e}"
            log(f"[{name}] erro: {st['error']}")
            continue
        st["fetched"] = len(raws)
        enriched = 0
        for raw in raws:
            # BLOQUEIO ABSOLUTO DE VAGAS FORA DE TI / PROGRAMAÇÃO
            if _FORBIDDEN_TITLES.search(raw.title) and not _REQUIRED_TECH_TERMS.search(raw.title):
                st["filtered"] += 1
                continue
            
            if not _REQUIRED_TECH_TERMS.search(raw.title) and not _REQUIRED_TECH_TERMS.search(raw.description[:500] if raw.description else ""):
                st["filtered"] += 1
                continue

            if raw.posted_at and raw.posted_at < cutoff:
                st["filtered"] += 1
                continue

            existing = db.scalar(select(Job).where(Job.source == raw.source, Job.external_id == raw.external_id))
            if existing:
                existing.last_seen, existing.active = now(), True
                continue

            if db.scalar(select(Job.id).where(Job.dedupe_key == dedupe_key(raw.company, raw.title, raw.location)).limit(1)):
                st["duplicates"] += 1
                continue

            if not raw.description and enriched < 30:
                try:
                    raw = col.enrich(raw)
                    enriched += 1
                except Exception as e:
                    log(f"[{name}] não foi possível obter descrição de {raw.external_id}: {e}")
            
            job = create_job(db, raw)
            score(db, job, ctx)
            st["new"] += 1
        db.commit()
        log(f"[{name}] {st}")

    for j in db.scalars(select(Job).where(Job.active.is_(True), Job.last_seen < now() - timedelta(days=15))):
        j.active = False
    db.commit()
    return {"sources": stats, "new_total": sum(s["new"] for s in stats.values())}


def rescore_all(db: Session) -> int:
    ctx = ctx_for_matching(db)
    jobs = list(db.scalars(select(Job)))
    for j in jobs:
        score(db, j, ctx)
    db.commit()
    return len(jobs)


# ---------- currículos ----------
def _resume_inputs(db: Session):
    doc = profile_doc(db)
    return doc, [s["name"] for s in doc["skills"]]


def generate_resume(db: Session, lang: str, job: Job | None = None) -> Resume:
    doc, skills = _resume_inputs(db)
    jskills = [r.skill for r in job.requirements] if job else None
    content = builder.build_content(doc, doc["experiences"], doc["education"], skills, lang, jskills)
    unverified = builder.find_unverified(content, skills, [doc["summary"]] + [e["description"] for e in doc["experiences"]]
                                         + [" ".join(e["technologies"]) for e in doc["experiences"]])
    slug = re.sub(r"[^a-z0-9]+", "-", (job.company + "-" + job.title if job else "base").lower()).strip("-")[:60]
    stamp = now().strftime("%Y%m%d-%H%M%S")
    folder = Path(settings.GENERATED_DIR) / lang
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{slug}-{stamp}"
    builder.write_pdf(content, str(base) + ".pdf")
    builder.write_docx(content, str(base) + ".docx")
    r = Resume(language=lang, kind="generated", label=(f"{job.company} — {job.title}" if job else f"Currículo base gerado ({lang})"),
               filename=base.name + ".pdf", path=str(base) + ".pdf", docx_path=str(base) + ".docx", job_id=job.id if job else None,
               text=builder.flat_text(content), meta={"warnings": content["warnings"], "unverified_skills": unverified})
    db.add(r)
    db.commit()
    return r


def best_resume_for(db: Session, job: Job) -> Resume | None:
    q = select(Resume).where(Resume.job_id == job.id).order_by(Resume.id.desc())
    r = db.scalar(q)
    if r:
        return r
    for lang in (job.language, "en", "pt"):
        r = db.scalar(select(Resume).where(Resume.kind == "base", Resume.language == lang, Resume.is_active.is_(True)).order_by(Resume.id.desc()))
        if r:
            return r
    return None


def _start_of_day():
    return now().replace(hour=0, minute=0, second=0, microsecond=0)


def today_by_tier(db: Session, include_queued: bool = True) -> dict:
    cond = Application.prepared_at >= _start_of_day()
    if include_queued:
        cond = cond | Application.status.in_(["queued", "preparing", "submitting"])
    out = {t: 0 for t in TIERS}
    for a in db.scalars(select(Application).where(cond)).unique():
        t = tier_of(a.job)
        if t in out:
            out[t] += 1
    return out


def shortlist(db: Session, progress=None) -> int:
    prefs = profile_doc(db)["preferences"]
    q = (select(Job).join(JobMatch).where(JobMatch.score >= float(prefs.get("min_score", 40)), JobMatch.eliminated.is_(False),
                                          Job.active.is_(True), Job.dismissed.is_(False)).order_by(JobMatch.score.desc()))
    cands = {t: [] for t in TIERS}
    for job in db.scalars(q):
        t = tier_of(job)
        if t in cands and not db.scalar(select(Application.id).where(Application.job_id == job.id)):
            cands[t].append(job)
    take = allocate({t: len(v) for t, v in cands.items()}, prefs.get("focus", {"bh": 30, "brazil": 50, "remote": 20}),
                    int(prefs.get("shortlist_batch", 30)))
    chosen = [j for t in TIERS for j in cands[t][:take[t]]]
    for i, job in enumerate(chosen):
        if progress:
            progress({"phase": "shortlist", "label": f"Gerando currículo {i + 1}/{len(chosen)}: {job.title[:50]}", "done": i, "total": len(chosen)})
        res = None
        if settings.AUTO_GENERATE_RESUMES:
            try:
                res = generate_resume(db, job.language if job.language in builder.LABELS else "en", job)
            except Exception:
                traceback.print_exc()
        db.add(Application(job_id=job.id, resume_id=res.id if res else None, status="shortlisted"))
        db.commit()
    return len(chosen)
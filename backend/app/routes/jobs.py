import hashlib
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..collectors.base import RawJob
from ..db import get_db
from ..models import Application, Job, JobMatch
from ..automation import filler
from ..services import jobs_service as js

router = APIRouter(prefix="/jobs", tags=["jobs"])


def out(j: Job, full: bool = False) -> dict:
    m = j.match
    d = {
        "id": j.id, "source": j.source, "title": j.title, "company": j.company, "location": j.location, "remote": j.remote,
        "url": j.url, "language": j.language, "salary": j.salary, "seniority": j.seniority, "active": j.active,
        "dismissed": j.dismissed, "posted_at": j.posted_at.isoformat() if j.posted_at else None,
        "first_seen": j.first_seen.isoformat(), "tier": js.tier_of(j), "auto_lane": filler.is_auto_lane(j.url),
        "score": m.score if m else None, "eliminated": m.eliminated if m else False
    }
    if full:
        d.update(
            description=j.description,
            requirements=[{"skill": r.skill, "mandatory": r.mandatory} for r in j.requirements],
            matched=m.matched if m else [], gaps=m.gaps if m else [], breakdown=m.breakdown if m else {},
            explanation=m.explanation if m else ""
        )
    return d


@router.get("")
def list_jobs(q: str = "", source: str = "", tier: str = "", min_score: float = 0, hide_eliminated: bool = True,
              include_dismissed: bool = False, sort: str = "score", limit: int = 100, offset: int = 0,
              db: Session = Depends(get_db)):
    stmt = select(Job).join(JobMatch, isouter=True).where(Job.active.is_(True))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Job.title).like(like) | func.lower(Job.company).like(like))
    if source:
        stmt = stmt.where(Job.source == source)
    if min_score:
        stmt = stmt.where(JobMatch.score >= min_score)
    if hide_eliminated:
        stmt = stmt.where((JobMatch.eliminated.is_(False)) | (JobMatch.id.is_(None)))
    if not include_dismissed:
        stmt = stmt.where(Job.dismissed.is_(False))

    stmt = stmt.order_by(Job.first_seen.desc() if sort == "recent" else JobMatch.score.desc().nulls_last(), Job.id.desc())

    if tier:
        # Se for 'national', junta vagas de BH e Brasil
        if tier == "national":
            rows = [j for j in db.scalars(stmt.limit(3000)).unique() if js.tier_of(j) in ("bh", "brazil")]
        else:
            rows = [j for j in db.scalars(stmt.limit(3000)).unique() if js.tier_of(j) == tier]
        return {"total": len(rows), "items": [out(j) for j in rows[offset:offset + min(limit, 300)]]}

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return {"total": total, "items": [out(j) for j in db.scalars(stmt.limit(min(limit, 300)).offset(offset)).unique()]}


@router.get("/{jid}")
def get(jid: int, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404)
    app = db.scalar(select(Application).where(Application.job_id == jid))
    return {**out(j, full=True), "application_id": app.id if app else None}


class ManualJob(BaseModel):
    title: str
    company: str = ""
    url: str = ""
    location: str = ""
    description: str = ""
    remote: bool = False


@router.post("/manual")
def manual(body: ManualJob, db: Session = Depends(get_db)):
    raw = RawJob("manual", "m-" + hashlib.sha1(f"{body.url}|{body.title}|{body.company}".encode()).hexdigest()[:16],
                 body.title, body.company, body.location, body.remote, body.url, body.description)
    existing = db.scalar(select(Job).where(Job.source == "manual", Job.external_id == raw.external_id))
    job = existing or js.create_job(db, raw)
    js.score(db, job)
    db.commit()
    return out(job, full=True)


@router.post("/{jid}/rescore")
def rescore(jid: int, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404)
    js.set_requirements(db, j)
    js.score(db, j)
    db.commit()
    return out(j, full=True)


@router.post("/{jid}/dismiss")
def dismiss(jid: int, undo: bool = False, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404)
    j.dismissed = not undo
    db.commit()
    return {"ok": True}
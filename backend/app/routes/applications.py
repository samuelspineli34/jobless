from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Application, ApplicationAnswer, Job, now
from ..automation import filler
from ..matching.tiers import TIERS, allocate
from ..scheduler.worker import enqueue
from ..services.control import get_control
from ..services.profile_service import profile_doc
from ..services import jobs_service as js

router = APIRouter(prefix="/applications", tags=["applications"])
STATUSES = ["shortlisted", "queued", "preparing", "prepared", "needs_review", "submitting", "submitted", "failed",
            "interview", "rejected", "offer", "withdrawn"]


def out(a: Application) -> dict:
    return {"id": a.id, "job_id": a.job_id, "title": a.job.title, "company": a.job.company, "url": a.job.url, "source": a.job.source,
            "score": a.job.match.score if a.job.match else None, "tier": js.tier_of(a.job),
            "lane": "auto" if filler.is_auto_lane(a.job.url) else "manual", "status": a.status, "notes": a.notes, "resume_id": a.resume_id,
            "meta": a.meta or {}, "updated_at": a.updated_at.isoformat(),
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None}


@router.get("")
def list_apps(status: str = "", db: Session = Depends(get_db)):
    q = select(Application).order_by(Application.updated_at.desc())
    if status:
        q = q.where(Application.status == status)
    return [out(a) for a in db.scalars(q).unique()]


class CreateIn(BaseModel):
    job_id: int
    resume_id: int | None = None


@router.post("")
def create(body: CreateIn, db: Session = Depends(get_db)):
    job = db.get(Job, body.job_id)
    if not job:
        raise HTTPException(404, "vaga não encontrada")
    a = db.scalar(select(Application).where(Application.job_id == job.id))
    if not a:
        res = body.resume_id or (js.best_resume_for(db, job).id if js.best_resume_for(db, job) else None)
        a = Application(job_id=job.id, resume_id=res, status="shortlisted")
        db.add(a)
        db.commit()
    return out(a)


@router.post("/{aid}/prepare")
def prepare(aid: int, db: Session = Depends(get_db)):
    """Enfileira o preenchimento no navegador. NÃO envia: você revisa e envia (salvo AUTO_SUBMIT em plataformas confiáveis)."""
    a = db.get(Application, aid)
    if not a:
        raise HTTPException(404)
    if a.status in ("submitted", "submitting"):
        raise HTTPException(409, f"candidatura já está '{a.status}'")
    a.status = "queued"
    db.commit()
    return {"run_id": enqueue(db, "prepare_application", {"application_id": aid}).id}


class AssistedIn(BaseModel):
    count: int = 5


@router.post("/assisted")
def assisted(body: AssistedIn, db: Session = Depends(get_db)):
    """Modo assistido: enfileira as próximas N candidaturas (respeitando o foco BH/Brasil/remoto). Para cada uma o navegador
    abre preenchido; você revisa, envia e fecha a aba para passar à seguinte."""
    prefs = profile_doc(db)["preferences"]
    min_score = float(prefs.get("min_score", 60))
    by = {t: [] for t in TIERS}
    for a in db.scalars(select(Application).where(Application.status.in_(["shortlisted", "needs_review"]))).unique():
        j = a.job
        t = js.tier_of(j)
        if t in by and j.active and not j.dismissed and j.match and not j.match.eliminated and j.match.score >= min_score:
            by[t].append(a)
    n = max(1, min(body.count, 20))
    take = allocate({t: len(v) for t, v in by.items()}, prefs.get("focus", {}), n)
    ids = []
    for t in TIERS:
        for a in sorted(by[t], key=lambda x: -x.job.match.score)[:take[t]]:
            a.status = "queued"
            db.commit()
            ids.append(enqueue(db, "prepare_application", {"application_id": a.id}).id)
    return {"queued": len(ids)}


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)):
    import csv
    import io
    from fastapi.responses import Response
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "empresa", "vaga", "faixa", "fonte", "nota", "status", "enviada_em", "link", "notas"])
    for a in db.scalars(select(Application).order_by(Application.id)).unique():
        o = out(a)
        w.writerow([o["id"], o["company"], o["title"], o["tier"], o["source"], o["score"], o["status"], o["submitted_at"] or "", o["url"], o["notes"].replace("\n", " | ")])
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=candidaturas.csv"})


class PatchIn(BaseModel):
    status: str | None = None
    notes: str | None = None
    resume_id: int | None = None


@router.patch("/{aid}")
def patch(aid: int, body: PatchIn, db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if not a:
        raise HTTPException(404)
    if body.status:
        if body.status not in STATUSES:
            raise HTTPException(400, "status inválido")
        a.status = body.status
        if body.status == "submitted" and not a.submitted_at:
            a.submitted_at = now()
    if body.notes is not None:
        a.notes = body.notes
    if body.resume_id is not None:
        a.resume_id = body.resume_id
    db.commit()
    return out(a)


@router.get("/answers/all")
def answers(db: Session = Depends(get_db)):
    return [{"id": x.id, "pattern": x.pattern, "answer": x.answer, "approved": x.approved}
            for x in db.scalars(select(ApplicationAnswer).order_by(ApplicationAnswer.approved, ApplicationAnswer.id.desc()))]


class AnswerIn(BaseModel):
    pattern: str
    answer: str
    approved: bool = True


@router.post("/answers")
def save_answer(body: AnswerIn, db: Session = Depends(get_db)):
    x = db.scalar(select(ApplicationAnswer).where(ApplicationAnswer.pattern == body.pattern)) or ApplicationAnswer(pattern=body.pattern)
    x.answer, x.approved = body.answer, body.approved and bool(body.answer)
    db.add(x)
    db.commit()
    return {"id": x.id}


@router.delete("/answers/{xid}")
def delete_answer(xid: int, db: Session = Depends(get_db)):
    x = db.get(ApplicationAnswer, xid)
    if x:
        db.delete(x)
        db.commit()
    return {"ok": True}

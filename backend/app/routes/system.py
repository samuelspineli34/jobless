from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..automation import filler
from ..collectors import REGISTRY
from ..config import settings
from ..db import get_db
from ..models import Application, AutomationRun, Experience, Job, JobMatch, Profile, Resume, now
from ..matching.tiers import TIER_LABEL, TIERS, targets
from ..scheduler import worker
from ..services import jobs_service as js
from ..services.control import get_control, update_control
from ..services.profile_service import profile_doc

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    by_status = dict(db.execute(select(Application.status, func.count()).group_by(Application.status)).all())
    sent = by_status.get("submitted", 0) + by_status.get("interview", 0) + by_status.get("rejected", 0) + by_status.get("offer", 0)
    answered = by_status.get("interview", 0) + by_status.get("rejected", 0) + by_status.get("offer", 0)
    n_exp = db.scalar(select(func.count()).select_from(Experience)) or 0
    prof = db.scalar(select(Profile).limit(1))
    resume_langs = sorted({lang for (lang,) in db.execute(select(Resume.language).where(Resume.kind == "base", Resume.is_active.is_(True)))})
    jobs_total = db.scalar(select(func.count()).select_from(Job).where(Job.active.is_(True))) or 0
    setup = {"profile_ok": bool(prof and prof.full_name and n_exp), "resume_langs": resume_langs,
             "collected": jobs_total > 0,
             "collecting": bool(db.scalar(select(AutomationRun.id).where(AutomationRun.kind == "collect", AutomationRun.status.in_(["pending", "running"])))),
             "any_application": bool(sum(by_status.values()))}
    ctl = get_control(db)
    prefs = profile_doc(db)["preferences"]
    focus = prefs.get("focus", {"bh": 85, "brazil": 5, "remote": 10})
    tg, done = targets(int(ctl["daily_limit"]), focus), js.today_by_tier(db, include_queued=False)
    min_score = float(prefs.get("min_score", 60))
    avail = {t: 0 for t in TIERS}
    for j in db.scalars(select(Job).where(Job.active.is_(True), Job.dismissed.is_(False))):
        if j.match and not j.match.eliminated and j.match.score >= min_score and js.tier_of(j) in avail:
            avail[js.tier_of(j)] += 1
    waiting = sum(1 for a in db.scalars(select(Application).where(Application.status == "shortlisted")).unique() if not filler.is_auto_lane(a.job.url))
    return {
        "setup": setup,
        "control": ctl, "focus": focus,
        "quota": [{"tier": t, "label": TIER_LABEL[t], "percent": focus.get(t, 0), "target": tg[t], "done": done[t], "available": avail[t]} for t in TIERS],
        "funnel": {k: sum(by_status.get(x, 0) for x in xs) for k, xs in {
            "shortlisted": ("shortlisted", "queued", "preparing", "prepared", "needs_review", "submitting", "submitted", "interview", "offer", "rejected"),
            "prepared": ("prepared", "needs_review", "submitting", "submitted", "interview", "offer", "rejected"),
            "submitted": ("submitted", "interview", "offer", "rejected"),
            "answered": ("interview", "offer", "rejected"), "interview": ("interview", "offer")}.items()},
        "waiting_manual": waiting,
        "jobs_total": db.scalar(select(func.count()).select_from(Job).where(Job.active.is_(True))) or 0,
        "jobs_new_24h": db.scalar(select(func.count()).select_from(Job).where(Job.first_seen >= now() - timedelta(hours=24))) or 0,
        "jobs_above_min": db.scalar(select(func.count()).select_from(JobMatch).where(JobMatch.score >= 60, JobMatch.eliminated.is_(False))) or 0,
        "applications": by_status, "response_rate": round(100 * answered / sent, 1) if sent else None,
        "prepared_today": filler.applications_today(db), "daily_limit": ctl["daily_limit"],
        "paused": ctl["paused"], "auto_submit": ctl["auto_submit"],
        "sources": [{"name": c.name, "label": c.label} for c in REGISTRY.values()],
        "failed_runs": db.scalar(select(func.count()).select_from(AutomationRun).where(AutomationRun.status == "failed")) or 0,
    }


class RunIn(BaseModel):
    kind: str
    payload: dict = {}


@router.post("/runs")
def create_run(body: RunIn, db: Session = Depends(get_db)):
    if body.kind not in ("collect", "rescore", "generate_resume"):
        raise HTTPException(400, "tipo inválido")
    return {"id": worker.enqueue(db, body.kind, body.payload).id}


@router.get("/runs")
def runs(limit: int = 25, db: Session = Depends(get_db)):
    return [{"id": r.id, "kind": r.kind, "status": r.status, "detail": r.detail, "log": r.log[-2000:], "payload": r.payload,
             "created_at": r.created_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in db.scalars(select(AutomationRun).order_by(AutomationRun.id.desc()).limit(limit))]


class SettingsIn(BaseModel):
    auto_apply: bool | None = None
    auto_submit: bool | None = None
    daily_limit: int | None = None


@router.post("/control/settings")
def control_settings(body: SettingsIn, db: Session = Depends(get_db)):
    kw = {k: v for k, v in body.model_dump().items() if v is not None}
    if "daily_limit" in kw:
        kw["daily_limit"] = max(1, min(200, kw["daily_limit"]))
    return update_control(db, **kw)


@router.post("/control/{action}")
def control(action: str, db: Session = Depends(get_db)):
    if action == "pause":
        worker.set_paused(db, True)
    elif action == "resume":
        worker.set_paused(db, False)
    elif action == "stop":     # interrompe imediatamente qualquer automação de navegador e pausa a fila
        worker.set_paused(db, True)
        filler.stop_event.set()
    else:
        raise HTTPException(400)
    return {"paused": worker.is_paused(db)}

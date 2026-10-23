"""Fila persistente (tabela automation_runs) + worker em thread + agendador periódico.
Estados: pending -> running -> completed | needs_review | failed. Reiniciar o PC não perde nada:
runs 'running' voltam para 'pending' na inicialização (e o filler nunca reenvia uma candidatura 'submitting')."""
import threading
import traceback

from sqlalchemy import select

from ..automation import filler
from ..config import settings
from ..db import SessionLocal
from ..models import Application, AutomationRun, now
from ..services.control import get_control, update_control

AUTOMATION_KINDS = {"prepare_application"}
_shutdown = threading.Event()
_thread: threading.Thread | None = None
_scheduler = None


def is_paused(db) -> bool:
    return bool(get_control(db)["paused"])


def set_paused(db, paused: bool) -> None:
    update_control(db, paused=paused)
    if not paused:
        filler.stop_event.clear()


def enqueue(db, kind: str, payload: dict | None = None) -> AutomationRun:
    if kind in ("collect", "auto_apply"):   # nunca duas coletas/rodadas automáticas ao mesmo tempo
        dup = db.scalar(select(AutomationRun).where(AutomationRun.kind == kind, AutomationRun.status.in_(["pending", "running"])))
        if dup:
            return dup
    run = AutomationRun(kind=kind, status="pending", payload=payload or {})
    db.add(run)
    db.commit()
    return run


def auto_apply(db) -> int:
    """Piloto automático: escolhe candidaturas 'shortlisted' das plataformas confiáveis (Greenhouse/Lever) respeitando
    o limite diário e o foco BH/Brasil/remoto, e as enfileira. As demais ficam 'Aguardando você'."""
    from ..matching.tiers import TIERS, allocate
    from ..services import jobs_service as js
    from ..services.profile_service import profile_doc
    ctl = get_control(db)
    if not ctl["auto_apply"] or ctl["paused"]:
        return 0
    prefs = profile_doc(db)["preferences"]
    min_score = float(prefs.get("min_score", 60))
    by_tier = {t: [] for t in TIERS}
    for a in db.scalars(select(Application).where(Application.status == "shortlisted")).unique():
        j = a.job
        if (filler.is_auto_lane(j.url) and j.active and not j.dismissed and j.match and not j.match.eliminated
                and j.match.score >= min_score and js.tier_of(j) in by_tier):
            by_tier[js.tier_of(j)].append(a)
    take = allocate({t: len(v) for t, v in by_tier.items()}, prefs.get("focus", {}), int(ctl["daily_limit"]), js.today_by_tier(db))
    n = 0
    for t in TIERS:
        for a in sorted(by_tier[t], key=lambda x: -x.job.match.score)[:take[t]]:
            a.status = "queued"
            db.commit()
            enqueue(db, "prepare_application", {"application_id": a.id, "auto": True})
            n += 1
    return n


def _handle(db, run: AutomationRun) -> dict:
    from ..services import jobs_service as js
    from ..models import Job
    def prog(d):   # progresso ao vivo para as barras do Painel
        run.detail = d
        db.commit()

    if run.kind == "collect":
        lines = []
        res = js.run_collect(db, log=lines.append, progress=prog)
        res["shortlisted"] = js.shortlist(db, progress=prog)
        res["auto_queued"] = auto_apply(db)
        run.log = "\n".join(lines)
        return res
    if run.kind == "rescore":
        n = js.rescore_all(db)
        return {"rescored": n, "shortlisted": js.shortlist(db, progress=prog), "auto_queued": auto_apply(db)}
    if run.kind == "auto_apply":
        return {"auto_queued": auto_apply(db)}
    if run.kind == "generate_resume":
        job = db.get(Job, run.payload["job_id"]) if run.payload.get("job_id") else None
        r = js.generate_resume(db, run.payload.get("lang", "en"), job)
        return {"resume_id": r.id}
    if run.kind == "prepare_application":
        lines = []
        res = filler.prepare(db, int(run.payload["application_id"]), log=lines.append, auto=bool(run.payload.get("auto")))
        run.log = "\n".join(lines)
        return res
    raise ValueError(f"tipo desconhecido: {run.kind}")


def _loop():
    while not _shutdown.is_set():
        with SessionLocal() as db:
            q = select(AutomationRun).where(AutomationRun.status == "pending").order_by(AutomationRun.id).limit(1)
            if is_paused(db):
                q = q.where(AutomationRun.kind.notin_(AUTOMATION_KINDS))
            run = db.scalar(q)
            if not run:
                pass
            else:
                run.status, run.started_at = "running", now()
                db.commit()
                try:
                    res = _handle(db, run)
                    run.status = "needs_review" if res.get("status") == "needs_review" else "failed" if res.get("status") == "failed" else "completed"
                    run.detail = res
                except filler.Stopped as e:
                    db.rollback()
                    run.status, run.log = "failed", f"{run.log}\n{e}"
                except Exception:
                    db.rollback()
                    run.status, run.log = "failed", f"{run.log}\n{traceback.format_exc()}"
                run.finished_at = now()
                db.merge(run)
                db.commit()
                continue
        _shutdown.wait(3)


def start():
    global _thread, _scheduler
    with SessionLocal() as db:
        for r in db.scalars(select(AutomationRun).where(AutomationRun.status == "running")):
            r.status = "pending"   # retoma
        db.commit()
    with SessionLocal() as db:   # primeira abertura do dia: coleta sozinho se já há perfil e faz tempo desde a última
        from datetime import timedelta
        from ..models import Experience
        last = db.scalar(select(AutomationRun.created_at).where(AutomationRun.kind == "collect").order_by(AutomationRun.id.desc()).limit(1))
        has_profile = db.scalar(select(Experience.id).limit(1)) is not None
        if has_profile and settings.SCHEDULER_ENABLED and (not last or last < now() - timedelta(hours=settings.COLLECT_INTERVAL_HOURS)):
            enqueue(db, "collect")
    _shutdown.clear()
    _thread = threading.Thread(target=_loop, name="job-worker", daemon=True)
    _thread.start()
    if settings.SCHEDULER_ENABLED:
        from apscheduler.schedulers.background import BackgroundScheduler

        def tick():
            with SessionLocal() as db:
                enqueue(db, "collect")

        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(tick, "interval", hours=settings.COLLECT_INTERVAL_HOURS, id="collect")

        def tick_auto():
            with SessionLocal() as db:
                enqueue(db, "auto_apply")

        _scheduler.add_job(tick_auto, "interval", hours=1, id="auto_apply")
        _scheduler.start()


def stop():
    _shutdown.set()
    if _scheduler:
        _scheduler.shutdown(wait=False)

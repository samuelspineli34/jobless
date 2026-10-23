"""Estado de controle persistido no banco (sobrevive a reinícios): pausa, piloto automático, envio automático, limite diário."""
from ..config import settings
from ..models import Setting

DEFAULTS = {"paused": False, "auto_apply": True, "auto_submit": True, "daily_limit": settings.DAILY_APPLICATION_LIMIT}


def get_control(db) -> dict:
    s = db.get(Setting, "control")
    return {**DEFAULTS, **(s.value if s else {})}


def update_control(db, **kw) -> dict:
    s = db.get(Setting, "control") or Setting(key="control", value={})
    s.value = {**(s.value or {}), **kw}
    db.merge(s)
    db.commit()
    return get_control(db)

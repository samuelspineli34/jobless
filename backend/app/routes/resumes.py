import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Job, Resume
from ..resumes.builder import SUPPORTED
from ..services import jobs_service as js
from ..services import profile_import as pi
from ..services.profile_service import merge_import

router = APIRouter(prefix="/resumes", tags=["resumes"])


def out(r: Resume) -> dict:
    return {"id": r.id, "language": r.language, "kind": r.kind, "label": r.label, "filename": r.filename, "job_id": r.job_id,
            "has_docx": bool(r.docx_path), "meta": r.meta or {}, "is_active": r.is_active, "created_at": r.created_at.isoformat()}


@router.get("")
def list_resumes(kind: str | None = None, db: Session = Depends(get_db)):
    q = select(Resume).order_by(Resume.id.desc())
    if kind:
        q = q.where(Resume.kind == kind)
    return [out(r) for r in db.scalars(q)]


@router.post("/upload")
async def upload(file: UploadFile = File(...), language: str = Form(...), import_to_profile: bool = Form(False),
                 db: Session = Depends(get_db)):
    """Guarda um PDF base (ex.: resume_pt-BR.pdf / resume_en.pdf). Um ativo por idioma; os anteriores ficam no histórico."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Envie um PDF")
    language = language.lower().split("-")[0]
    data = await file.read()
    folder = Path(settings.RESUMES_DIR) / language
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", file.filename)
    path = folder / f"{js.now().strftime('%Y%m%d-%H%M%S')}-{safe}"
    path.write_bytes(data)
    try:
        text = pi.read_pdf_text(data)
    except Exception:
        text = ""
    for old in db.scalars(select(Resume).where(Resume.kind == "base", Resume.language == language, Resume.is_active.is_(True))):
        old.is_active = False
    r = Resume(language=language, kind="base", label=f"Currículo base ({language})", filename=safe, path=str(path), text=text, is_active=True)
    db.add(r)
    db.commit()
    imported = merge_import(db, pi.parse_resume_text(text)) if (import_to_profile and text) else None
    return {"resume": out(r), "imported": imported}


class GenerateIn(BaseModel):
    language: str
    job_id: int | None = None


@router.post("/generate")
def generate(body: GenerateIn, db: Session = Depends(get_db)):
    if body.language not in SUPPORTED:
        raise HTTPException(400, f"Idiomas suportados: {', '.join(SUPPORTED)}")
    job = db.get(Job, body.job_id) if body.job_id else None
    return out(js.generate_resume(db, body.language, job))


@router.get("/{rid}/download")
def download(rid: int, fmt: str = "pdf", db: Session = Depends(get_db)):
    r = db.get(Resume, rid)
    if not r:
        raise HTTPException(404)
    path = r.docx_path if fmt == "docx" and r.docx_path else r.path
    if not path or not Path(path).exists():
        raise HTTPException(404, "arquivo não encontrado")
    return FileResponse(path, filename=Path(path).name)


@router.delete("/{rid}")
def delete(rid: int, db: Session = Depends(get_db)):
    r = db.get(Resume, rid)
    if not r:
        raise HTTPException(404)
    for p in (r.path, r.docx_path):
        if p:
            Path(p).unlink(missing_ok=True)
    db.delete(r)
    db.commit()
    return {"ok": True}

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import profile_import as pi
from ..services.profile_service import merge_import, profile_doc, save_profile_doc
from ..services.translate import translate_profile

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileDoc(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    headline: str = ""
    summary: str = ""
    links: dict = Field(default_factory=dict)
    languages: list[dict] = Field(default_factory=list)
    preferences: dict = Field(default_factory=dict)
    i18n: dict = Field(default_factory=dict)
    experiences: list[dict] = Field(default_factory=list)
    education: list[dict] = Field(default_factory=list)
    skills: list[dict] = Field(default_factory=list)


@router.get("")
def get(db: Session = Depends(get_db)):
    return profile_doc(db)


@router.put("")
def put(doc: ProfileDoc, db: Session = Depends(get_db)):
    save_profile_doc(db, doc.model_dump())
    return profile_doc(db)


@router.post("/import")
async def import_file(file: UploadFile = File(...), replace: bool = False, db: Session = Depends(get_db)):
    """Aceita: PDF de currículo, PDF do LinkedIn ('Salvar como PDF') ou ZIP do 'Obter cópia dos seus dados' do LinkedIn."""
    data = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".zip"):
            parsed = pi.parse_linkedin_zip(data)
        elif name.endswith(".pdf"):
            parsed = pi.parse_resume_text(pi.read_pdf_text(data))
        else:
            raise HTTPException(400, "Envie um .pdf (currículo/LinkedIn) ou .zip (exportação de dados do LinkedIn)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Não consegui ler o arquivo: {e}")
    counts = merge_import(db, parsed, replace=replace)
    return {"imported": counts, "profile": profile_doc(db),
            "note": "Revise os dados importados: a leitura de PDF é heurística, o ZIP do LinkedIn é mais confiável."}


@router.post("/translate/{lang}")
def translate(lang: str, db: Session = Depends(get_db)):
    try:
        return {"translated_fields": translate_profile(db, lang)}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Falha na tradução: {e}")

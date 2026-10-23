"""Tradução OPCIONAL do perfil para outros idiomas usando a API da Anthropic (precisa de ANTHROPIC_API_KEY).
O prompt proíbe acrescentar fatos; o resultado fica salvo em i18n e pode ser editado antes de gerar o currículo."""
import json
import re

from ..config import settings

NAMES = {"pt": "Brazilian Portuguese", "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian"}
SYSTEM = ("You are a faithful résumé translator. Translate every JSON value into {lang}. Never add, remove, exaggerate or "
          "invent facts, numbers, dates, employers or technologies. Keep technology and product names unchanged. "
          "Keep line breaks and bullet markers. Return ONLY a valid JSON object with exactly the same keys.")


def translate_strings(strings: dict[str, str], lang: str) -> dict[str, str]:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("Defina ANTHROPIC_API_KEY no .env para traduzir automaticamente (ou edite as traduções à mão).")
    if lang not in NAMES:
        raise ValueError("idioma não suportado")
    import httpx
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120,
                   headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                   json={"model": settings.ANTHROPIC_MODEL, "max_tokens": 4000, "system": SYSTEM.format(lang=NAMES[lang]),
                         "messages": [{"role": "user", "content": json.dumps(strings, ensure_ascii=False)}]})
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    out = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip())
    return {k: str(out.get(k, "")) for k in strings}


def translate_profile(db, lang: str) -> int:
    from ..models import Education, Experience
    from sqlalchemy import select
    from .profile_service import get_profile
    p = get_profile(db)
    items = {"p.summary": p.summary, "p.headline": p.headline}
    exps, edus = list(db.scalars(select(Experience))), list(db.scalars(select(Education)))
    items.update({f"e{e.id}": e.description for e in exps if e.description})
    items.update({f"d{e.id}": e.degree for e in edus if e.degree})
    items = {k: v for k, v in items.items() if v}
    if not items:
        return 0
    tr = translate_strings(items, lang)
    p.i18n = {**(p.i18n or {}), lang: {"summary": tr.get("p.summary", ""), "headline": tr.get("p.headline", "")}}
    for e in exps:
        if f"e{e.id}" in tr:
            e.i18n = {**(e.i18n or {}), lang: {"description": tr[f"e{e.id}"]}}
    for e in edus:
        if f"d{e.id}" in tr:
            e.i18n = {**(e.i18n or {}), lang: {"degree": tr[f"d{e.id}"]}}
    db.commit()
    return len(tr)

"""Tradução opcional do perfil para outros idiomas usando a mesma API configurada no .env (Groq / OpenAI)."""
import json
import os
import re
import httpx

from ..config import settings
from .ai_answer import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

NAMES = {"pt": "Brazilian Portuguese", "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian"}
SYSTEM = (
    "You are a faithful résumé translator. Translate every JSON value into {lang}. "
    "Never add, remove, exaggerate or invent facts, numbers, dates, employers or technologies. "
    "Keep technology and product names unchanged. Keep line breaks and bullet markers. "
    "Return ONLY a valid JSON object with exactly the same keys."
)


def translate_strings(strings: dict[str, str], lang: str) -> dict[str, str]:
    if lang not in NAMES:
        raise ValueError("Idioma não suportado")

    anthropic_key = settings.ANTHROPIC_API_KEY
    target_lang_name = NAMES[lang]

    if anthropic_key:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages", timeout=120,
            headers={
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": settings.ANTHROPIC_MODEL,
                "max_tokens": 4000,
                "system": SYSTEM.format(lang=target_lang_name),
                "messages": [{"role": "user", "content": json.dumps(strings, ensure_ascii=False)}]
            }
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    elif LLM_API_KEY:
        # Corrige o endpoint para apontar limpo para a Groq (/openai/v1/chat/completions)
        base_url = LLM_BASE_URL.rstrip("/")
        if not base_url.endswith("/chat/completions"):
            endpoint = f"{base_url}/chat/completions"
        else:
            endpoint = base_url

        headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
        prompt = (
            f"{SYSTEM.format(lang=target_lang_name)}\n\n"
            f"Translate the following JSON object values into {target_lang_name}. Output ONLY valid JSON:\n"
            f"{json.dumps(strings, ensure_ascii=False)}"
        )
        body = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": f"You are a professional translator to {target_lang_name}. Output strictly valid JSON format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 4000
        }
        r = httpx.post(endpoint, headers=headers, json=body, timeout=120)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
    else:
        raise RuntimeError("Defina GROQ_API_KEY ou ANTHROPIC_API_KEY no arquivo .env para traduzir o perfil.")

    cleaned_text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    out = json.loads(cleaned_text)
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
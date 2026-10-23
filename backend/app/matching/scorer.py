"""Pontuação explicável: regras determinísticas sobre perfil x vaga. Sem LLM, sem caixa-preta."""
import re
from datetime import date

from ..services.skills import LEVELS, display, level_index
from .tiers import TIER_LABEL, location_tier

DEFAULT_WEIGHTS = {"technical": 35, "experience": 25, "seniority": 15, "location": 15, "language": 10}
_RESTRICTED = re.compile(r"(us only|usa only|u\.s\. only|united states only|must (?:be )?(?:located|reside) in the (?:us|u\.s\.|united states)|"
                         r"uk only|work authorization|authorized to work in the (?:us|united states))", re.I)
_STOPWORDS = {"the", "and", "de", "da", "do", "para", "senior", "junior", "pleno", "sr", "jr", "i", "ii", "iii", "remote", "remoto"}


def _ym(s: str | None) -> int | None:
    if not s:
        return None
    m = re.match(r"(\d{4})(?:-(\d{2}))?", s)
    return int(m.group(1)) * 12 + (int(m.group(2)) - 1 if m.group(2) else 0) if m else None


def total_years(experiences: list[dict]) -> float:
    """Anos de experiência somando a união dos intervalos (sem contar sobreposições)."""
    today = date.today().year * 12 + date.today().month - 1
    spans = sorted((_ym(e.get("start")), _ym(e.get("end")) or today) for e in experiences if _ym(e.get("start")))
    total, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return round(total / 12, 1)


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-zà-ÿ+#]{3,}", (s or "").lower()) if t not in _STOPWORDS}


def score_job(job: dict, ctx: dict) -> dict:
    """job: title, description, location, remote, language, seniority, years_required, company, requirements[(skill, mandatory)]
       ctx: skills(set), years(float), titles(list), prefs(dict), languages(set)"""
    prefs, w = ctx["prefs"], {**DEFAULT_WEIGHTS, **ctx["prefs"].get("weights", {})}
    mine = set(ctx["skills"])
    req = [s for s, m in job["requirements"] if m]
    nice = [s for s, m in job["requirements"] if not m]
    matched = [s for s in req + nice if s in mine]
    gaps = [s for s in req if s not in mine]

    # 1) técnica
    if req or nice:
        mr, mn = [s for s in req if s in mine], [s for s in nice if s in mine]
        technical = (len(mr) + 0.5 * len(mn)) / (len(req) + 0.5 * len(nice))
        tnote = f"{len(matched)} de {len(req) + len(nice)} tecnologias da vaga"
    else:
        technical, tnote = 0.5, "nenhuma tecnologia reconhecida na descrição (nota neutra)"

    # 2) experiência (título + anos)
    jt = _tokens(job["title"])
    title_sim = max([len(jt & _tokens(t)) / len(jt) for t in ctx["titles"]] or [0]) if jt else 0
    yreq = job.get("years_required")
    years_fit = 0.8 if yreq is None else min(1.0, ctx["years"] / yreq)
    experience = 0.6 * title_sim + 0.4 * years_fit
    enote = f"título {title_sim:.0%} parecido; {ctx['years']:.1f} anos de experiência" + (f" para {yreq} exigidos" if yreq else "")

    # 3) senioridade
    jl, preferred = job.get("seniority") or "", [x for x in prefs.get("seniority", ["junior", "mid", "senior"]) if x in LEVELS]
    if not jl:
        seniority, snote = 0.7, "senioridade não informada"
    elif jl in preferred or not preferred:
        seniority, snote = 1.0, f"nível {jl} dentro do desejado"
    else:
        dist = min(abs(level_index(jl) - level_index(p)) for p in preferred)
        seniority, snote = (0.5 if dist == 1 else 0.15), f"nível {jl} fora do desejado ({', '.join(preferred)})"

    # 4) localização / regime — faixas: Belo Horizonte > Brasil > remoto
    where = f"{job.get('location', '')} {'remote' if job.get('remote') else ''}".lower()
    
    # Chamada corrigida usando o import relativo correto (.tiers)
    tier = location_tier(job.get("location", ""), job["title"], bool(job.get("remote")), job.get("language", ""), job.get("description", ""))
    
    restricted = bool(_RESTRICTED.search(job.get("description", "")[:3000] + " " + where))
    if tier == "bh":
        location, lnote = 1.0, "Belo Horizonte / Grande BH"
    elif tier == "brazil":
        location, lnote = 0.9, "Brasil"
    elif tier == "remote" and restricted:
        location, lnote = 0.2, "remoto, mas com restrição de país/autorização de trabalho"
    elif tier == "remote" and prefs.get("accept_remote_global", True):
        location, lnote = 0.85, "remoto global sem restrição aparente de país"
    elif tier == "remote":
        location, lnote = 0.3, "remoto internacional restrito"
    else:
        location, lnote = 0.0, f"fora das localizações desejadas ({job.get('location') or 'n/d'})"

    # 5) idioma
    language = 1.0 if job.get("language", "en") in ctx["languages"] else 0.3
    inote = f"vaga em {job.get('language', 'en')}" + ("" if language == 1.0 else " (idioma não listado no perfil)")

    parts = {"technical": technical, "experience": experience, "seniority": seniority, "location": location, "language": language}
    score = round(100 * sum(w[k] * v for k, v in parts.items()) / sum(w[k] for k in parts), 1)

    # eliminatórios
    blob_title_desc = f"{job['title']} {job.get('description', '')[:500]}".lower()
    is_tech = bool(re.search(
        r"(software|developer|engineer|desenvolvedor|engenheiro|programador|devops|sre|qa|"
        r"python|javascript|typescript|java|react|node|fullstack|backend|frontend|arquiteto|tech lead|dados|it)",
        blob_title_desc
    ))
    is_commercial_noise = bool(re.search(r"\b(sales engineer|account executive|risk analyst|financial analyst)\b", job["title"].lower()))

    if not is_tech or is_commercial_noise:
        return {
            "score": 0, "eliminated": True, "matched": [], "gaps": [], 
            "breakdown": {"technical": 0, "experience": 0, "seniority": 0, "location": 0, "language": 0},
            "explanation": "ELIMINADA: Vaga fora do escopo de programação, desenvolvimento ou TI.",
            "tier": "other"
        }
        
    eliminated = []
    blob = f"{job['title']} {job.get('description', '')}".lower()
    for kw in prefs.get("exclude_keywords", []):
        if kw and kw.lower() in blob:
            eliminated.append(f"contém '{kw}'")
    if job.get("company", "").lower() in [c.lower() for c in prefs.get("blocked_companies", [])]:
        eliminated.append("empresa bloqueada")
    if prefs.get("hard_location") and tier == "other":
        eliminated.append("localização incompatível (fora do Brasil/BH/Remoto)")

    explanation = (f"Técnica: {tnote}. Experiência: {enote}. Senioridade: {snote}. "
                   f"Local: {lnote}. Idioma: {inote}." + (f" ELIMINADA: {'; '.join(eliminated)}." if eliminated else ""))
    return {"score": score, "eliminated": bool(eliminated), "matched": [display(s) for s in matched],
            "gaps": [display(s) for s in gaps], "breakdown": {k: round(v * 100) for k, v in parts.items()},
            "explanation": explanation, "tier": tier}
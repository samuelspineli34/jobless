"""Preenchimento de candidaturas com Playwright e suporte a respostas por IA."""
import re
import threading
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Application, ApplicationAnswer, Job, Resume, now
from ..services.control import get_control
from ..services.jobs_service import best_resume_for
from ..services.profile_service import profile_doc
from ..services.ai_answer import generate_answer

stop_event = threading.Event()
TRUSTED_SUBMIT = ("boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co")

FIELD_RULES = [
    ("e-?mail", "email"),
    (r"first\s*name|given name|primeiro nome|vorname|pr[ée]nom", "first"),
    (r"last\s*name|family name|surname|sobrenome|nachname|nom de famille", "last"),
    (r"full name|nome completo|^name\b|^nome\b|your name|seu nome", "full"),
    (r"phone|telefone|celular|mobile|whats", "phone"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"website|portfolio|portf[óo]lio|site pessoal|personal site", "website"),
    (r"\bcity\b|cidade|location|localiza|where are you based", "location"),
]
CAPTCHA_SEL = "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], .g-recaptcha, .h-captcha, [data-sitekey]"
LABEL_JS = """el => { let t=''; const id=el.id;
 if(id){const l=document.querySelector('label[for="'+CSS.escape(id)+'"]'); if(l) t=l.innerText;}
 if(!t){const l=el.closest('label'); if(l) t=l.innerText;}
 if(!t) t=el.getAttribute('aria-label')||'';
 if(!t){const lb=el.getAttribute('aria-labelledby'); if(lb) t=lb.split(' ').map(i=>(document.getElementById(i)||{}).innerText||'').join(' ');}
 if(!t) t=el.placeholder||el.name||'';
 return t.trim(); }"""
SUCCESS_RE = re.compile(r"thank you|application (?:has been )?(?:submitted|received)|obrigad[oa]|candidatura (?:enviada|recebida)|we.ve received", re.I)


class Stopped(Exception):
    pass


def platform_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return "greenhouse" if "greenhouse.io" in host else "lever" if "lever.co" in host else "linkedin" if "linkedin.com" in host else "generic"


def _values(doc: dict) -> dict:
    parts = (doc["full_name"] or "").split()
    links = doc.get("links", {})
    return {
        "email": doc["email"], "first": parts[0] if parts else "", "last": " ".join(parts[1:]), "full": doc["full_name"],
        "phone": doc["phone"], "linkedin": links.get("linkedin", ""), "github": links.get("github", ""),
        "website": links.get("website") or links.get("portfolio") or links.get("github", ""), "location": doc["location"]
    }


def _check_stop():
    if stop_event.is_set():
        raise Stopped("Interrompido pelo usuário")


def applications_today(db: Session) -> int:
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(Application).where(Application.prepared_at >= start)) or 0


def is_auto_lane(url: str) -> bool:
    return urlparse(url).netloc.lower() in TRUSTED_SUBMIT


def company_applied_recently(db: Session, app: Application, days: int = 30) -> bool:
    return bool(db.scalar(select(Application.id).join(Job, Job.id == Application.job_id).where(
        Job.company == app.job.company, Application.id != app.id, Application.submitted_at >= now() - timedelta(days=days)).limit(1)))


def prepare(db: Session, application_id: int, log=print, auto: bool = False) -> dict:
    app = db.get(Application, application_id)
    if not app:
        raise ValueError("Candidatura não encontrada")
    if app.status in ("submitted", "interview", "offer", "rejected"):
        return {"status": "completed", "note": f"Já {app.status}; nada a fazer"}
    if app.status == "submitting":
        app.status, app.notes = "needs_review", (app.notes + "\nEnvio interrompido: confira no site se foi enviada.").strip()
        db.commit()
        return {"status": "needs_review", "note": "Estado de envio incerto"}

    ctl = get_control(db)
    if applications_today(db) >= ctl["daily_limit"]:
        app.status = "shortlisted"
        db.commit()
        return {"status": "failed", "note": f"Limite diário ({ctl['daily_limit']}) atingido"}

    job = app.job
    if auto and company_applied_recently(db, app):
        app.status, app.notes = "shortlisted", (app.notes + "\nCandidatura enviada para esta empresa nos últimos 30 dias; retida para revisão.").strip()
        db.commit()
        return {"status": "needs_review", "note": "Empresa já recebeu candidatura recente"}

    plat = platform_of(job.url)
    if plat == "linkedin":
        app.status = "needs_review"
        app.notes = (app.notes + "\nVaga do LinkedIn: abra o link e aplique manualmente (Easy Apply não automatizado por segurança da conta).").strip()
        db.commit()
        return {"status": "needs_review", "note": "LinkedIn não é automatizado"}

    resume = db.get(Resume, app.resume_id) if app.resume_id else best_resume_for(db, job)
    if not resume or not resume.path:
        raise RuntimeError("Nenhum currículo disponível: envie um base ou gere um para a vaga.")
    app.resume_id, app.status = resume.id, "preparing"
    db.commit()

    doc = profile_doc(db)
    vals = _values(doc)
    answers = {a.pattern.lower(): a.answer for a in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.approved.is_(True)))}
    filled, unknown, captcha, submitted, confirmed = [], [], False, False, False
    questions_map = {}

    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(settings.BROWSER_PROFILE_DIR), headless=settings.HEADLESS or (auto and not captcha),
                                                    viewport={"width": 1280, "height": 900})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
            _check_stop()

            btn = page.locator("a:has-text('Apply'), button:has-text('Apply'), a:has-text('Candidatar'), "
                               "button:has-text('Candidatar'), a:has-text('Candidate-se'), button:has-text('Candidate-se')").first
            if btn.count() and not page.locator("input[type=file]").count():
                try:
                    btn.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except PWTimeout:
                    pass
            page.wait_for_timeout(1500)
            captcha = page.locator(CAPTCHA_SEL).count() > 0

            fields = page.locator("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=search]), textarea, select")
            files = page.locator("input[type=file]")

            for i in range(fields.count()):
                _check_stop()
                el = fields.nth(i)
                try:
                    ftype = (el.get_attribute("type") or el.evaluate("e => e.tagName").lower()).lower()
                    if ftype == "file" or not el.is_visible():
                        continue
                    label = el.evaluate(LABEL_JS)
                    if not label:
                        continue
                    low = label.lower()
                    required = bool(el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true" or "*" in label)

                    # 1. Tentar regras diretas de perfil
                    value = next((vals[k] for pat, k in FIELD_RULES if re.search(pat, low) and vals.get(k)), None)

                    # 2. Tentar banco de respostas aprovadas
                    if value is None:
                        for p_, ans_ in answers.items():
                            if p_ in low or re.search(re.escape(p_), low):
                                value = ans_
                                break

                    # 3. Gerar via IA e salvar como pendente
                    if value is None and required and ftype in ("text", "textarea", "input"):
                        lang = "pt" if job.language == "pt" or "brasil" in job.location.lower() else "en"
                        value = generate_answer(label, doc, language=lang)
                        pat_key = label.rstrip(" *:")[:290]
                        questions_map[pat_key] = value

                        # Persiste a resposta sugerida no banco
                        existing_ans = db.scalar(select(ApplicationAnswer).where(ApplicationAnswer.pattern == pat_key))
                        if not existing_ans:
                            db.add(ApplicationAnswer(pattern=pat_key, answer=value, approved=False))
                        elif not existing_ans.answer:
                            existing_ans.answer = value
                        db.commit()

                    if value is not None and ftype in ("text", "email", "tel", "url", "textarea", "number", "input"):
                        el.fill(str(value))
                        filled.append(label[:80])
                    elif required and ftype not in ("hidden",):
                        unknown.append(label[:200])
                except Exception as e:
                    log(f"Campo ignorado: {e}")

            uploaded = False
            for i in range(files.count()):
                lab = ""
                try:
                    lab = files.nth(i).evaluate(LABEL_JS).lower()
                except Exception:
                    pass
                if not re.search(r"cover|carta", lab):
                    files.nth(i).set_input_files(resume.path)
                    uploaded = True
                    break
            if not uploaded:
                unknown.append("(upload do currículo não encontrado)")

            can_submit = (ctl["auto_submit"] and urlparse(page.url).netloc.lower() in TRUSTED_SUBMIT and not unknown and not captcha)
            if can_submit:
                app.status = "submitting"
                db.commit()
                page.locator("button[type=submit], input[type=submit], button:has-text('Submit'), button:has-text('Enviar')").first.click(timeout=8000)
                page.wait_for_timeout(4000)
                submitted = True
                confirmed = bool(SUCCESS_RE.search(page.inner_text("body")))
                app.status = "submitted" if confirmed else "needs_review"
                app.submitted_at = now() if confirmed else None
            else:
                app.status = "needs_review" if (unknown or captcha) else "prepared"
                deadline = 0 if (auto and not captcha and settings.HEADLESS) else settings.REVIEW_WAIT_MINUTES * 60
                waited = 0
                while waited < deadline and not page.is_closed() and not stop_event.is_set():
                    page.wait_for_timeout(1000)
                    waited += 1
        finally:
            ctx.close()

    app.prepared_at = now()
    app.meta = {
        "filled": filled,
        "unknown": list(dict.fromkeys(unknown)),
        "questions_generated": questions_map,
        "captcha": captcha,
        "platform": plat,
        "auto_submitted": submitted,
        "confirmed": confirmed
    }
    if unknown or captcha:
        app.notes = (app.notes + f"\nPendências: {', '.join(app.meta['unknown'])}{' | CAPTCHA detectado (resolva na tela)' if captcha else ''}").strip()
    db.commit()
    return {"status": "needs_review" if app.status == "needs_review" else "completed", "application_status": app.status, **app.meta}
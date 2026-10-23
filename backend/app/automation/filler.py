"""Preenchimento automatizado de candidaturas com Playwright e integração de IA."""
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
TRUSTED_SUBMIT = ("boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "gupy.io", "workday.com")

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
 if(!t){const fs=el.closest('fieldset'); if(fs){const lg=fs.querySelector('legend'); if(lg) t=lg.innerText;}}
 if(!t){const q=el.closest('[data-qa], .application-question, .field, .form-group'); if(q) {const x=q.querySelector('label, legend, [class*=label], [class*=question]'); if(x) t=x.innerText;}}
 if(!t) t=el.placeholder||el.name||'';
 return t.replace(/\\s+/g, ' ').trim(); }"""
SUCCESS_RE = re.compile(r"thank you|application (?:has been )?(?:submitted|received)|obrigad[oa]|candidatura (?:enviada|recebida)|we.ve received", re.I)


class Stopped(Exception):
    pass


def platform_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return "greenhouse" if "greenhouse.io" in host else "lever" if "lever.co" in host else "gupy" if "gupy.io" in host else "linkedin" if "linkedin.com" in host else "generic"


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
    return "linkedin.com" not in urlparse(url).netloc.lower()


def company_applied_recently(db: Session, app: Application, days: int = 30) -> bool:
    return bool(db.scalar(select(Application.id).join(Job, Job.id == Application.job_id).where(
        Job.company == app.job.company, Application.id != app.id, Application.submitted_at >= now() - timedelta(days=days)).limit(1)))


def prepare(db: Session, application_id: int, log=print, auto: bool = False) -> dict:
    app = db.get(Application, application_id)
    if not app:
        raise ValueError("Candidatura não encontrada")
    if app.status in ("submitted", "interview", "offer", "rejected"):
        return {"status": "completed", "note": f"Já {app.status}; nada a fazer"}

    job = app.job
    plat = platform_of(job.url)
    if plat == "linkedin":
        app.status = "needs_review"
        app.notes = "Vaga do LinkedIn: abra o link e aplique manualmente."
        db.commit()
        return {"status": "needs_review", "note": "LinkedIn não automatizado"}

    ctl = get_control(db)
    resume = db.get(Resume, app.resume_id) if app.resume_id else best_resume_for(db, job)
    if not resume or not resume.path:
        raise RuntimeError("Nenhum currículo disponível.")
    app.resume_id, app.status = resume.id, "preparing"
    db.commit()

    doc = profile_doc(db)
    vals = _values(doc)
    
    approved_answers = {a.pattern.lower().strip(): a.answer for a in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.approved.is_(True)))}
    
    filled, unknown, captcha, submitted, confirmed = [], [], False, False, False
    questions_map = {}

    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
    import os
    
    brave_path = "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
    if not os.path.exists(brave_path):
        brave_path = "C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"

    launch_args = {
        "headless": settings.HEADLESS or auto,
        "viewport": {"width": 1280, "height": 900}
    }
    if os.path.exists(brave_path):
        launch_args["executable_path"] = brave_path

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(settings.BROWSER_PROFILE_DIR), **launch_args)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
            _check_stop()

            btn = page.locator("a:has-text('Apply'), button:has-text('Apply'), a:has-text('Candidatar'), button:has-text('Candidatar')").first
            if btn.count() and not page.locator("input[type=file]").count() and not page.locator("form input:not([type=hidden]), form textarea, form select").count():
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
                    if not label or len(label) < 2:
                        continue
                    
                    low = label.lower().strip()
                    required = bool(el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true" or "*" in label)

                    value = next((vals[k] for pat, k in FIELD_RULES if re.search(pat, low) and vals.get(k)), None)

                    if value is None:
                        for p_, ans_ in approved_answers.items():
                            if p_ in low or low in p_:
                                value = ans_
                                break

                    if value is None and ftype in ("text", "textarea", "input"):
                        value = generate_answer(label, doc)
                        clean_pattern = re.sub(r"\s+", " ", label).strip().rstrip(" *:")[:290]
                        questions_map[clean_pattern] = value

                        existing_ans = db.scalar(select(ApplicationAnswer).where(ApplicationAnswer.pattern == clean_pattern))
                        if not existing_ans:
                            db.add(ApplicationAnswer(pattern=clean_pattern, answer=value, approved=False))
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

            # CORRIGIDO: usa o dicionário ctl obtido dinamicamente do banco
            can_submit = (bool(ctl.get("auto_submit", False)) and plat in ("greenhouse", "lever") and not unknown and not captcha)
            if can_submit:
                app.status = "submitting"
                db.commit()
                try:
                    submit_btn = page.locator("button[type=submit], input[type=submit], button:has-text('Submit'), button:has-text('Enviar')").first
                    if submit_btn.count() > 0:
                        submit_btn.click(timeout=8000)
                        page.wait_for_timeout(4000)
                        submitted = True
                        confirmed = bool(SUCCESS_RE.search(page.inner_text("body")))
                        app.status = "submitted" if confirmed else "needs_review"
                        app.submitted_at = now() if confirmed else None
                    else:
                        app.status = "needs_review"
                except Exception:
                    app.status = "needs_review"
            else:
                app.status = "needs_review" if (unknown or captcha) else "prepared"
        finally:
            ctx.close()

    app.prepared_at = now()
    app.meta = {"filled": filled, "unknown": list(dict.fromkeys(unknown)), "captcha": captcha}
    app.notes = f"IA preencheu {len(filled)} campos. {'Enviado com sucesso.' if submitted else 'Aguardando revisão ou envio.'}"
    db.commit()
    return {"status": "needs_review" if app.status == "needs_review" else "completed", "application_status": app.status, **app.meta}
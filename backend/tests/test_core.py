import io
import zipfile

from app.matching.scorer import score_job, total_years
from app.matching.tiers import allocate, location_tier, targets
from app.resumes.builder import build_content, find_unverified, write_docx, write_pdf
from app.services.profile_import import parse_linkedin_zip, parse_resume_text, read_pdf_text, to_ym
from app.services.skills import detect_language, detect_seniority, extract_skills, normalize_skill, split_requirements, years_required

RESUME = """João Silva
Desenvolvedor Full-Stack
joao@example.com | +55 31 99999-1234 | linkedin.com/in/joaosilva | github.com/joaosilva
Resumo
Desenvolvedor com foco em Python, TypeScript e PostgreSQL.
Experiência Profissional
Acme Tecnologia
Desenvolvedor Pleno
Jan 2022 - Presente
Belo Horizonte, MG
- Construí APIs com Flask e SQLAlchemy
- Dashboards em React e TypeScript
Beta Sistemas
Desenvolvedor Júnior
Mar 2020 - Dez 2021
- Automação com Python e Selenium
Formação
UFMG
Bacharelado em Sistemas de Informação (2016 - 2020)
Competências
Python, Docker, Git, PostgreSQL
Idiomas
Português (Nativo)
Inglês (Avançado)
"""


def make_pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return buf.getvalue()


def test_skills_and_levels():
    s = extract_skills("Python, FastAPI, PostgreSQL, Node.js, C++, CI/CD. Java e JavaScript")
    assert {"python", "fastapi", "postgresql", "node.js", "c++", "ci/cd", "java", "javascript"} <= set(s)
    assert normalize_skill("Postgres") == "postgresql"
    assert detect_seniority("Software Engineer II") == "mid"
    assert detect_seniority("Desenvolvedor Pleno") == "mid"
    assert detect_seniority("Senior Backend Engineer") == "senior"
    assert years_required("5+ years of experience") == 5
    assert detect_language("Estamos buscando uma pessoa para a nossa equipe com experiência") == "pt"
    req, nice = split_requirements("Requisitos: Python e Flask. " * 10 + " Diferencial: Kafka")
    assert "Kafka" in nice and "Kafka" not in req


def test_parse_resume_text_and_pdf_roundtrip():
    d = parse_resume_text(read_pdf_text(make_pdf(RESUME)))
    assert d["full_name"] == "João Silva" or d["full_name"].startswith("Jo")
    assert d["email"] == "joao@example.com"
    assert "linkedin" in d["links"] and "github" in d["links"]
    assert {"python", "flask", "react", "postgresql"} <= set(d["skills"])
    assert len(d["experiences"]) == 2
    e0 = d["experiences"][0]
    assert e0["company"] == "Acme Tecnologia" and "Pleno" in e0["title"] and e0["start"] == "2022-01" and e0["end"] is None
    assert d["experiences"][1]["end"] == "2021-12"
    assert {x["code"] for x in d["languages"]} == {"pt", "en"}
    assert d["education"] and d["education"][0]["institution"] == "UFMG"


def test_linkedin_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Profile.csv", "First Name,Last Name,Headline,Summary,Geo Location\nMaria,Souza,Dev,Sobre mim,Brasil\n")
        z.writestr("Positions.csv", "Company Name,Title,Description,Location,Started On,Finished On\nAcme,Dev Backend,Python e Docker,BH,Mar 2021,\n")
        z.writestr("Skills.csv", "Name\nPython\nPostgreSQL\n")
        z.writestr("Languages.csv", "Name,Proficiency\nEnglish,Full professional\n")
    d = parse_linkedin_zip(buf.getvalue())
    assert d["full_name"] == "Maria Souza" and d["experiences"][0]["start"] == "2021-03" and d["experiences"][0]["end"] is None
    assert "python" in d["skills"] and d["languages"][0]["code"] == "en"
    assert to_ym("março de 2021") == "2021-03" and to_ym("Present") is None


CTX = {"skills": {"python", "flask", "postgresql", "docker"}, "years": 4.0, "titles": ["Backend Developer", "Software Engineer"],
       "languages": {"pt", "en"}, "prefs": {"seniority": ["junior", "mid"], "locations": ["brazil", "remote"], "exclude_keywords": ["php"]}}


def job(**kw):
    base = {"title": "Python Backend Developer", "description": "", "location": "Brazil", "remote": True, "language": "en",
            "seniority": "mid", "years_required": 3, "company": "X", "requirements": [("python", True), ("flask", True), ("kafka", False)]}
    return {**base, **kw}


def test_scorer_explains_and_eliminates():
    r = score_job(job(), CTX)
    assert r["score"] > 70 and "Python" in r["matched"] and not r["eliminated"] and "Técnica" in r["explanation"]
    bad = score_job(job(requirements=[("java", True), ("spring", True)], seniority="lead", location="Berlin", remote=False), CTX)
    assert bad["score"] < r["score"] - 25 and "Java" in bad["gaps"]
    assert score_job(job(description="we use PHP"), CTX)["eliminated"]
    assert score_job(job(description="US only, work authorization required", location="Remote"),
                     {**CTX, "prefs": {**CTX["prefs"], "locations": ["brazil"]}})["breakdown"]["location"] < 30


def test_total_years_union():
    assert total_years([{"start": "2020-01", "end": "2022-01"}, {"start": "2021-01", "end": "2023-01"}]) == 3.0


def test_resume_build_multilang_and_validation(tmp_path):
    profile = {"full_name": "João Silva", "email": "j@x.com", "headline": "Dev", "summary": "Resumo em pt", "links": {"github": "https://github.com/j"},
               "languages": [{"code": "pt", "level": "Nativo"}], "preferences": {"content_language": "pt"},
               "i18n": {"en": {"summary": "Summary in English"}}}
    exps = [{"title": "Dev", "company": "Acme", "start": "2022-01", "end": None, "description": "- API com Flask", "technologies": ["flask"], "i18n": {}}]
    en = build_content(profile, exps, [], ["python", "docker", "flask"], "en", job_skills=["flask"])
    assert en["skills"][0] == "Flask" and en["summary"] == "Summary in English"
    assert "description" in en["warnings"]            # descrição ainda não traduzida -> aviso
    assert en["experiences"][0]["period"].endswith("Present")
    pt = build_content(profile, exps, [], ["python"], "pt")
    assert pt["warnings"] == [] and pt["labels"]["experience"] == "Experiência Profissional"
    assert find_unverified(en, ["python", "docker", "flask"], ["API com Flask"]) == []
    en["summary"] += " Também uso Kubernetes."
    assert find_unverified(en, ["python"], []) == ["flask", "kubernetes"] or "kubernetes" in find_unverified(en, ["python"], [])
    write_pdf(pt, str(tmp_path / "a.pdf")); write_docx(pt, str(tmp_path / "a.docx"))
    assert "João Silva" in read_pdf_text((tmp_path / "a.pdf").read_bytes())
    assert (tmp_path / "a.docx").stat().st_size > 2000


def test_tiers_and_allocation():
    assert location_tier("Belo Horizonte, MG") == "bh" and location_tier("Contagem, Minas Gerais, Brasil") == "bh"
    assert location_tier("São Paulo, SP") == "brazil" and location_tier("Remoto, Brasil", remote=True) == "brazil"
    assert location_tier("", remote=True, language="pt") == "brazil" and location_tier("Worldwide", remote=True, language="en") == "remote"
    assert location_tier("Berlin, Germany") == "other"
    f = {"bh": 85, "brazil": 5, "remote": 10}
    assert targets(20, f) == {"bh": 17, "brazil": 1, "remote": 2} and sum(targets(10, f).values()) == 10
    assert allocate({"bh": 30, "brazil": 10, "remote": 10}, f, 20) == {"bh": 17, "brazil": 1, "remote": 2}
    # poucas vagas em BH: a sobra vai para Brasil e depois remoto, sem passar do limite
    r = allocate({"bh": 3, "brazil": 10, "remote": 10}, f, 20)
    assert r["bh"] == 3 and sum(r.values()) == 20
    # descontando o que já foi feito hoje
    assert allocate({"bh": 30, "brazil": 10, "remote": 10}, f, 20, {"bh": 17, "brazil": 1, "remote": 0}) == {"bh": 0, "brazil": 0, "remote": 2}
    assert sum(allocate({"bh": 5, "brazil": 0, "remote": 0}, f, 20).values()) == 5

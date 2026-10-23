"""Importa perfil a partir de PDF de currículo, PDF do LinkedIn ("Salvar como PDF") ou do
arquivo de dados do LinkedIn (ZIP com Profile.csv, Positions.csv...). Tudo local, sem scraping."""
import csv
import io
import re
import zipfile

from .skills import extract_skills

SECTIONS = {
    "summary": ["summary", "about", "resumo", "resumo profissional", "perfil", "perfil profissional", "sobre", "objetivo", "profile", "resumen", "zusammenfassung"],
    "experience": ["experience", "work experience", "professional experience", "experiência", "experiência profissional", "experiencia", "experiencia profesional", "histórico profissional", "employment", "berufserfahrung", "expérience", "expérience professionnelle"],
    "education": ["education", "formação", "formação acadêmica", "formacao academica", "educação", "escolaridade", "educación", "ausbildung", "formation", "bildung"],
    "skills": ["skills", "top skills", "competências", "principais competências", "habilidades", "conhecimentos", "tecnologias", "technologies", "technical skills", "fähigkeiten", "compétences", "habilidades técnicas"],
    "languages": ["languages", "idiomas", "sprachen", "langues"],
    "other": ["certifications", "licenses & certifications", "projects", "publications", "honors-awards", "honors & awards", "courses", "certificações", "projetos", "cursos", "prêmios", "publicações", "interesses", "contact", "contato", "contacto", "kontakt", "references", "referências"],
}
_HEAD = {a: sec for sec, names in SECTIONS.items() for a in names}

_MONTHS = {"jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7,
           "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}
_DATE = r"(?:(?:jan|fev|feb|mar|abr|apr|mai|may|jun|jul|ago|aug|set|sep|out|oct|nov|dez|dec)[a-zç]*\.?\s+(?:de\s+)?)?(?:19|20)\d{2}"
_NOW = r"presente|present|atual|current|hoje|heute|actualidad|aujourd'hui|now"
RANGE = re.compile(rf"({_DATE})\s*(?:-|–|—|to|até|bis)\s*({_DATE}|{_NOW})", re.I)
_ROLE = re.compile(r"engineer|developer|desenvolvedor|analista|analyst|manager|designer|lead|intern|estagi|arquiteto|"
                   r"consultant|specialist|cientista|scientist|programador|head|coordenador|devops|sre|qa|tester|"
                   r"engenheiro|assistente|gerente|diretor|director|ceo|cto|freelance", re.I)
_LANGS = {"portuguese": "pt", "português": "pt", "portugues": "pt", "english": "en", "inglês": "en", "ingles": "en",
          "spanish": "es", "espanhol": "es", "español": "es", "french": "fr", "francês": "fr", "frances": "fr",
          "german": "de", "alemão": "de", "alemao": "de", "italian": "it", "italiano": "it"}


def read_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def to_ym(s: str | None) -> str | None:
    """'Mar 2021' / 'março de 2021' / '2021' -> '2021-03' / '2021'. None se for 'atual' ou vazio."""
    if not s:
        return None
    s = s.strip()
    if re.fullmatch(_NOW, s, re.I):
        return None
    year = re.search(r"(?:19|20)\d{2}", s)
    if not year:
        return None
    mon = re.match(r"([a-zç]{3})", s.lower())
    m = _MONTHS.get(mon.group(1)) if mon else None
    return f"{year.group(0)}-{m:02d}" if m else year.group(0)


def _heading(line: str) -> str | None:
    return _HEAD.get(re.sub(r"[:\s]+$", "", line.strip().lower()))


def _split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    head, secs, cur = [], {}, None
    for ln in lines:
        sec = _heading(ln)
        if sec:
            cur = sec
            secs.setdefault(sec, [])
            continue
        (head if cur is None else secs[cur]).append(ln)
    return head, secs


def _company_title(parts: list[str]) -> tuple[str, str]:
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        a, b = parts[-2], parts[-1]
        return (b, a) if _ROLE.search(a) and not _ROLE.search(b) else (a, b)
    if parts:
        one = parts[0]
        pieces = re.split(r"\s+(?:at|@|na|em|–|—|\|)\s+|\s+-\s+|,\s+", one, maxsplit=1)
        if len(pieces) == 2:
            a, b = pieces
            return (b, a) if _ROLE.search(a) else (a, b)
        return ("", one) if _ROLE.search(one) else (one, "")
    return "", ""


def _parse_experiences(lines: list[str]) -> list[dict]:
    idx = [i for i, l in enumerate(lines) if RANGE.search(l)]
    pres = []
    for n, i in enumerate(idx):
        lo = idx[n - 1] + 1 if n else 0
        pre, j = [], i - 1
        while j >= lo and len(pre) < 2 and lines[j].strip() and len(lines[j].strip()) <= 80:
            pre.insert(0, lines[j].strip())
            j -= 1
        pres.append(pre)
    out = []
    for n, i in enumerate(idx):
        m = RANGE.search(lines[i])
        inline = RANGE.sub("", lines[i]).strip(" ·|-–—,()")
        inline = re.sub(r"\(.*?(ano|year|mes|month).*?\)", "", inline, flags=re.I).strip(" ·|-–—,()")
        end_line = (idx[n + 1] - len(pres[n + 1])) if n + 1 < len(idx) else len(lines)
        desc = [l.strip() for l in lines[i + 1:end_line] if l.strip()]
        location = ""
        if desc and len(desc[0]) < 60 and not desc[0].startswith(("-", "•", "*")) and "," in desc[0]:
            location = desc.pop(0)
        company, title = _company_title(pres[n] + ([inline] if inline else []))
        out.append({"company": company, "title": title, "location": location, "start": to_ym(m.group(1)) or "",
                    "end": to_ym(m.group(2)), "description": "\n".join(desc),
                    "technologies": extract_skills(" ".join(desc) + " " + title), "source": "pdf"})
    return out


def _parse_education(lines: list[str]) -> list[dict]:
    lines = [l.strip() for l in lines if l.strip()]
    out = []
    for i, l in enumerate(lines):
        years = re.findall(r"(?:19|20)\d{2}", l)
        if years and i > 0:
            out.append({"institution": lines[i - 1], "degree": re.sub(r"[·(].*$", "", l).strip(" ,"),
                        "start": years[0] if len(years) > 1 else "", "end": years[-1]})
    if not out:
        out = [{"institution": l, "degree": "", "start": "", "end": None} for l in lines[:4]]
    return out


def _parse_languages(lines: list[str]) -> list[dict]:
    out = []
    for l in lines:
        low = l.strip().lower()
        for name, code in _LANGS.items():
            if low.startswith(name):
                lvl = re.search(r"\((.*?)\)", l)
                out.append({"code": code, "level": lvl.group(1) if lvl else ""})
                break
    return out


def parse_resume_text(text: str) -> dict:
    lines = [l.rstrip() for l in text.splitlines()]
    nonempty = [l.strip() for l in lines if l.strip()]
    head, secs = _split_sections(lines)
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone = re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)
    links = {}
    for key, pat in (("linkedin", r"linkedin\.com/in/[\w\-%]+"), ("github", r"github\.com/[\w\-]+")):
        m = re.search(pat, text, re.I)
        if m:
            links[key] = ("https://www." if key == "linkedin" else "https://") + m.group(0)
    name = headline = location = ""
    if nonempty and nonempty[0].lower() in ("contact", "contato", "contacto"):
        # PDF do LinkedIn: o bloco Contato/Competências/Idiomas vem antes do nome
        main = next((i for i, l in enumerate(lines) if _heading(l) in ("summary", "experience")), None)
        if main:
            cand = [l.strip() for l in lines[:main] if l.strip()][-3:]
            if len(cand) == 3:
                name, headline, location = cand
    if not name:
        clean = [l.strip() for l in head if l.strip() and "@" not in l and not re.search(r"\d{4}", l)]
        if clean:
            name = clean[0] if len(clean[0]) < 60 else ""
            headline = clean[1] if len(clean) > 1 and len(clean[1]) < 120 else ""
    skills = sorted(set(extract_skills(" ".join(secs.get("skills", [])))) | set(extract_skills(text)))
    return {
        "full_name": name, "email": email.group(0) if email else "",
        "phone": phone.group(1).strip() if phone else "", "location": location, "headline": headline,
        "summary": " ".join(l.strip() for l in secs.get("summary", [])).strip(), "links": links,
        "languages": _parse_languages(secs.get("languages", [])),
        "experiences": _parse_experiences(secs.get("experience", [])),
        "education": _parse_education(secs.get("education", [])), "skills": skills, "raw_text": text,
    }


def parse_linkedin_zip(data: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(data))
    files = {n.split("/")[-1].lower(): n for n in z.namelist()}

    def rows(name: str) -> list[dict]:
        if name.lower() not in files:
            return []
        raw = z.read(files[name.lower()]).decode("utf-8-sig", errors="replace")
        return list(csv.DictReader(io.StringIO(raw)))

    prof = (rows("Profile.csv") or [{}])[0]
    exps = [{
        "company": r.get("Company Name", ""), "title": r.get("Title", ""), "location": r.get("Location", ""),
        "start": to_ym(r.get("Started On")) or "", "end": to_ym(r.get("Finished On")),
        "description": r.get("Description", ""),
        "technologies": extract_skills(r.get("Description", "") + " " + r.get("Title", "")),
        "source": "linkedin"} for r in rows("Positions.csv")]
    edu = [{"institution": r.get("School Name", ""),
            "degree": ", ".join(x for x in (r.get("Degree Name"), r.get("Notes")) if x),
            "start": to_ym(r.get("Start Date")) or "", "end": to_ym(r.get("End Date"))} for r in rows("Education.csv")]
    skills = sorted({s for r in rows("Skills.csv") for s in extract_skills(r.get("Name", ""))} |
                    {s for e in exps for s in e["technologies"]})
    langs = []
    for r in rows("Languages.csv"):
        code = _LANGS.get((r.get("Name") or "").strip().lower())
        if code:
            langs.append({"code": code, "level": r.get("Proficiency", "")})
    email = (rows("Email Addresses.csv") or [{}])[0].get("Email Address", "")
    return {"full_name": f"{prof.get('First Name', '')} {prof.get('Last Name', '')}".strip(), "email": email,
            "phone": "", "location": prof.get("Geo Location", ""), "headline": prof.get("Headline", ""),
            "summary": prof.get("Summary", ""), "links": {}, "languages": langs, "experiences": exps,
            "education": edu, "skills": skills, "raw_text": ""}

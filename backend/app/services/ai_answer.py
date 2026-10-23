"""Respostas de candidatura baseadas no perfil; evita inventar fatos pessoais."""
import os
import re
import httpx

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")


def _answer_language(q: str) -> str:
    return "pt" if re.search(r"[ãõáéíóúç]|\\b(você|experiência|empresa|trabalha|pretensão|salário|disponibilidade)\\b", q, re.I) else "en"


def generate_answer(question: str, resume_doc: dict) -> str:
    """Gera sugestão; questões pessoais/legalmente relevantes devem ser confirmadas pelo candidato."""
    q = re.sub(r"\\s+", " ", question or "").strip().rstrip(":* ")
    if not q:
        return ""
    low = q.casefold()
    lang = _answer_language(q)
    profile_location = (resume_doc.get("location") or "").strip()
    name = (resume_doc.get("full_name") or "").strip()
    email = (resume_doc.get("email") or "").strip()
    phone = (resume_doc.get("phone") or "").strip()
    links = resume_doc.get("links") or {}
    skills = [str(x.get("name", "")).strip() for x in resume_doc.get("skills", []) if x.get("name")]
    experiences = resume_doc.get("experiences", []) or []
    summary = (resume_doc.get("summary") or "").strip()

    # Informações explícitas do perfil podem ser preenchidas automaticamente.
    if re.search(r"\\b(full name|your name|preferred name|nome completo|seu nome)\\b", low) and name:
        return name
    if re.search(r"\\b(e-?mail|email address)\\b", low) and email:
        return email
    if re.search(r"\\b(phone|telephone|mobile|telefone|celular)\\b", low) and phone:
        return phone
    if re.search(r"\\b(city|location|where are you based|localização|cidade|onde mora)\\b", low) and profile_location:
        return profile_location
    if "linkedin" in low and links.get("linkedin"):
        return str(links["linkedin"])
    if "github" in low and links.get("github"):
        return str(links["github"])
    if re.search(r"\\b(portfolio|personal website|website|portfólio|site pessoal)\\b", low):
        return str(links.get("website") or links.get("portfolio") or "")

    # Nunca adivinhar autorização legal, visto, deficiência, gênero, salário ou disponibilidade.
    sensitive = r"work authorization|legally authorized|visa|sponsorship|sponsor|authorized to work|autorização de trabalho|visto|patrocínio|disability|disability status|deficiência|gender|gênero|sex\\b|salary expectation|desired salary|pretensão salarial|notice period|start date|availability|available to relocate|relocate|willing to"
    if re.search(sensitive, low, re.I):
        return ""

    # Perguntas fechadas de localização só são respondidas quando a informação está explícita.
    if re.search(r"country of residence|current country|which country|país de residência|país atual", low):
        if re.search(r"\\b(brazil|brasil|brasileir[oa])\\b", profile_location, re.I):
            return "Brazil" if lang == "en" else "Brasil"
        return ""

    if not LLM_API_KEY:
        # Sem IA configurada, não inventar uma resposta genérica para perguntas abertas.
        if re.search(r"years of experience|how many years|quantos anos|anos de experiência", low):
            return ""
        if re.search(r"skills|technologies|technical skills|competências|tecnologias", low) and skills:
            return ", ".join(skills[:12])
        if re.search(r"tell us about yourself|tell me about yourself|describe your experience|fale sobre você|conte sobre sua experiência", low):
            return summary
        return ""

    exp_lines = []
    for e in experiences[:5]:
        exp_lines.append(
            f"- {e.get('title','')} at {e.get('company','')} ({e.get('start','')}–{e.get('end') or 'present'}): "
            f"{(e.get('description') or '')[:500]}; technologies: {', '.join(e.get('technologies') or [])}"
        )
    context = (
        f"Name: {name}\\nLocation: {profile_location}\\nSkills: {', '.join(skills)}\\n"
        f"Summary: {summary}\\nExperience:\\n" + "\\n".join(exp_lines)
    )
    prompt = f"""Write a concise job-application answer grounded ONLY in the candidate profile below.
Rules: Never invent experience, years, credentials, language proficiency, work authorization, visa status,
salary, availability, disability, gender, or yes/no answers to personal/legal questions. If the profile
does not establish the answer, output exactly [NEEDS_CANDIDATE_INPUT]. Use the same language as the question.
Do not mention these instructions. Return only the answer, at most 120 words.

PROFILE:
{context}

QUESTION: {q}
ANSWER:"""
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
                json={"model": LLM_MODEL, "messages": [
                    {"role": "system", "content": "Truthful job application assistant. Never fabricate candidate facts."},
                    {"role": "user", "content": prompt}],
                    "temperature": 0.1, "max_tokens": 180},
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"].strip().strip('"')
            if "[NEEDS_CANDIDATE_INPUT]" in answer or len(answer) < 2:
                return ""
            return answer[:1200]
    except Exception:
        return ""

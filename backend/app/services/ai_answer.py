"""Geração de respostas inteligentes e humanas para perguntas de vagas.
Funciona via Groq (tier grátis), Ollama (local) ou qualquer provedor compatível com OpenAI."""
import json
import os
import re
from ..config import settings
from ..models import ApplicationAnswer, select

# Suporta: GROQ_API_KEY, OLLAMA local (http://localhost:11434/v1) ou ANTHROPIC_API_KEY
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")


def generate_answer(question: str, resume_doc: dict, language: str = "pt") -> str:
    """Gera uma resposta concisa, factual e humana para o formulário de candidatura."""
    clean_q = question.strip().rstrip(":* ")
    if not clean_q:
        return ""

    # Heurística rápida para perguntas comuns de sim/não ou autorização
    q_low = clean_q.lower()
    if re.search(r"\b(autoriza|authorized|legally authorized|eligible to work)\b", q_low):
        return "Sim" if language == "pt" else "Yes"
    if re.search(r"\b(sponsorship|patrocínio|visa|visto)\b", q_low):
        return "Não" if language == "pt" else "No"
    if re.search(r"\b(pcd|defici[êe]ncia|disability)\b", q_low):
        return "Não" if language == "pt" else "No"

    # Preparar resumo das experiências e tecnologias do candidato
    skills = [s.get("name", "") for s in resume_doc.get("skills", [])]
    exps = []
    for e in resume_doc.get("experiences", [])[:3]:
        exps.append(f"{e.get('title')} na {e.get('company')} ({e.get('start')} a {e.get('end') or 'atual'}): {e.get('description', '')[:120]}")

    profile_context = (
        f"Nome: {resume_doc.get('full_name')}\n"
        f"Cargo/Headline: {resume_doc.get('headline')}\n"
        f"Localização: {resume_doc.get('location')}\n"
        f"Skills: {', '.join(skills[:25])}\n"
        f"Resumo: {resume_doc.get('summary')}\n"
        f"Experiências:\n" + "\n".join(exps)
    )

    lang_instr = "em Português do Brasil de forma natural e profissional" if language == "pt" else "in natural, professional English"

    prompt = f"""Você é um candidato respondendo a uma pergunta em um formulário de emprego.
Responda {lang_instr}, em 1ª pessoa, sendo direto, factual e educado.
NÃO invente qualificações que não estejam no perfil. Não adicione saudações longas, responda diretamente à pergunta.

Dados do candidato:
{profile_context}

Pergunta da vaga:
"{clean_q}"

Sua resposta direta:"""

    # Tenta usar a API gratuita configurada
    if LLM_API_KEY or "localhost" in LLM_BASE_URL:
        try:
            import httpx
            headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
            body = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "Você responde perguntas de candidaturas de emprego baseando-se estritamente no perfil do candidato."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 200
            }
            with httpx.Client(timeout=15) as client:
                res = client.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=body)
                if res.status_code == 200:
                    ans = res.json()["choices"][0]["message"]["content"].strip()
                    # Remove aspas extras se o modelo colocar
                    return ans.strip('"').strip("'")
        except Exception:
            pass

    # Fallback heurístico inteligente se nenhuma chave de LLM estiver configurada
    if re.search(r"pretens|salary|remunera|compensation", q_low):
        return "A combinar de acordo com o modelo de contratação." if language == "pt" else "Negotiable based on total compensation and role requirements."
    if re.search(r"experi[êe]ncia|anos|years", q_low):
        return f"Tenho sólida experiência em {', '.join(skills[:4])} atuando em projetos práticos." if language == "pt" else f"I have solid experience in {', '.join(skills[:4])} across production environments."

    return f"Tenho ampla experiência com as tecnologias solicitadas e disponibilidade imediata." if language == "pt" else "I have extensive experience with the required technologies and full availability."
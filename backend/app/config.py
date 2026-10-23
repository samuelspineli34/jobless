"""Configuração central, lida de variáveis de ambiente / arquivo .env na raiz."""
import os
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on", "sim")


_data = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()

settings = SimpleNamespace(
    ROOT=ROOT,
    DATA_DIR=_data,
    DATABASE_URL=os.getenv("DATABASE_URL") or f"sqlite:///{_data.as_posix()}/jobs.db",
    RESUMES_DIR=_data / "resumes",
    GENERATED_DIR=_data / "generated",
    BROWSER_PROFILE_DIR=_data / "browser-profile",
    FRONTEND_DIST=ROOT / "frontend" / "dist",
    USER_AGENT=os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    ),
    # agendamento
    COLLECT_INTERVAL_HOURS=float(os.getenv("COLLECT_INTERVAL_HOURS", "6")),
    SCHEDULER_ENABLED=_bool("SCHEDULER_ENABLED", True),
    # automação
    DAILY_APPLICATION_LIMIT=int(os.getenv("DAILY_APPLICATION_LIMIT", "20")),  # padrão inicial; editável no Painel
    HEADLESS=_bool("HEADLESS", False),
    REVIEW_WAIT_MINUTES=int(os.getenv("REVIEW_WAIT_MINUTES", "20")),
    AUTO_GENERATE_RESUMES=_bool("AUTO_GENERATE_RESUMES", True),
    # coleta
    HTTP_DELAY_SECONDS=float(os.getenv("HTTP_DELAY_SECONDS", "2")),
    # tradução opcional de currículos (Anthropic API)
    ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY", ""),
    ANTHROPIC_MODEL=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
)

for _d in (settings.DATA_DIR, settings.RESUMES_DIR, settings.GENERATED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

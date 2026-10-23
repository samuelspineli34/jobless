"""Teste de fumaça da API com SQLite temporário. Rode: cd backend && python -m pytest -q"""
import io
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SCHEDULER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.test_core import RESUME, make_pdf  # noqa: E402


def test_end_to_end_flow():
    with TestClient(app) as c:
        assert c.get("/api/health").json() == {"ok": True}
        # importa PDF -> perfil
        r = c.post("/api/profile/import", files={"file": ("cv.pdf", make_pdf(RESUME), "application/pdf")})
        assert r.status_code == 200 and r.json()["imported"]["experiences"] == 2
        prof = c.get("/api/profile").json()
        assert prof["email"] == "joao@example.com" and any(s["name"] == "python" for s in prof["skills"])
        # salva PDF base PT e EN
        for lang in ("pt", "en"):
            r = c.post("/api/resumes/upload", data={"language": lang}, files={"file": (f"resume_{lang}.pdf", make_pdf(RESUME), "application/pdf")})
            assert r.status_code == 200
        # vaga manual -> nota explicada
        job = c.post("/api/jobs/manual", json={"title": "Python Backend Developer Pleno", "company": "Acme", "location": "Remote",
                                                "remote": True, "description": "Requisitos: Python, Flask, PostgreSQL e Docker. Diferencial: Kafka." * 3}).json()
        assert job["score"] > 50 and "Python" in job["matched"]
        # currículo sob medida em inglês + espanhol
        for lang in ("en", "es"):
            r = c.post("/api/resumes/generate", json={"language": lang, "job_id": job["id"]})
            assert r.status_code == 200 and c.get(f"/api/resumes/{r.json()['id']}/download").status_code == 200
        # candidatura + controle
        a = c.post("/api/applications", json={"job_id": job["id"]}).json()
        assert a["status"] == "shortlisted" and a["resume_id"]
        assert c.post("/api/control/pause").json()["paused"] is True
        assert c.post("/api/control/resume").json()["paused"] is False
        st = c.get("/api/stats").json()
        assert st["jobs_total"] == 1 and st["control"]["auto_submit"] is True and st["control"]["auto_apply"] is True
        assert [q["tier"] for q in st["quota"]] == ["bh", "brazil", "remote"]
        assert sum(q["target"] for q in st["quota"]) == st["daily_limit"]
        assert c.post("/api/control/settings", json={"daily_limit": 40}).json()["daily_limit"] == 40
        assert c.get("/api/applications/export.csv").status_code == 200
        assert c.get("/api/jobs?tier=bh").status_code == 200
        assert c.get("/api/jobs").json()["total"] == 1

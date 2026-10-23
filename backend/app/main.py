from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routes import applications, jobs, profile, resumes, system
from .scheduler import worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Job Assistant", version="1.0.0", lifespan=lifespan)
# Só aceita o frontend local (Vite em dev). A API não deve ficar exposta fora da sua máquina.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
for r in (system.router, profile.router, resumes.router, jobs.router, applications.router):
    app.include_router(r, prefix="/api")

dist = settings.FRONTEND_DIST
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = dist / path
        return FileResponse(f if path and f.is_file() else dist / "index.html")

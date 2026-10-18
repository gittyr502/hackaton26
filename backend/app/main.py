from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.api import auth, batches, config, dashboard, export, forms, workflow
from app.config import get_settings
from app.db import get_engine, init_db
from app.models import Batch, Form, SourceFile
from app.debug_routes import router as debug_router


def recover_interrupted() -> None:
    """After a restart, work that was in flight is gone: mark it failed so it can be retried."""
    with Session(get_engine()) as s:
        for form in s.exec(select(Form).where(Form.status.in_(["pending", "processing"]))).all():
            form.status, form.error = "failed", "interrupted by server restart"
            s.add(form)
        for sf in s.exec(select(SourceFile).where(SourceFile.status.in_(["pending", "processing"]))).all():
            sf.status, sf.error = "failed", "interrupted by server restart"
            s.add(sf)
        for b in s.exec(select(Batch).where(Batch.status == "processing")).all():
            b.status = "done"
            s.add(b)
        s.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not get_settings().anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set: add it to .env (see .env.example)")
    init_db()
    recover_interrupted()
    yield


app = FastAPI(title="Commitment Forms", lifespan=lifespan)
app.include_router(debug_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(workflow.router)
app.include_router(dashboard.router)
app.include_router(batches.router)
app.include_router(export.router)
app.include_router(forms.router)
app.include_router(config.router)


@app.get("/api/health")
def health():
    return {"ok": True}

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import check_connection
from app.config import settings
from app.routers import campaigns, contacts, conversations, whatsapp
from app.services.scheduler_service import init_scheduler, shutdown_scheduler
from app.utils.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_scheduler()
    logger.info("Application started")
    yield
    shutdown_scheduler()
    logger.info("Application stopped")


app = FastAPI(
    title="WhatsApp Campaign Management System",
    description=(
        "Bulk WhatsApp messaging platform with Odoo contact sync, "
        "campaign scheduling, background processing, and delivery tracking."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.FRONTEND_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campaigns.router)
app.include_router(contacts.router)
app.include_router(conversations.router)
app.include_router(whatsapp.router)


@app.get("/", tags=["Health"])
def health():
    """Lightweight health check — must respond instantly for Render's probe."""
    return {"status": "running", "service": "whatsapp-campaign-manager", "version": "1.0.0"}


@app.get("/health/db", tags=["Health"])
def health_db():
    """Deep health check including database connectivity (may be slow)."""
    ok = check_connection()
    return {"database": "ok" if ok else "unreachable"}

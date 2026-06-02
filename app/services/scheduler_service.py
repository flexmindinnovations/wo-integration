import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

# Re-use the app's existing engine so APScheduler inherits the correct
# SSL settings (sslmode=require) and connection pool — avoids a second
# engine that would hang on Supabase's TLS handshake at startup.
from app.database import engine as _db_engine

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialised — call init_scheduler() first")
    return _scheduler


def init_scheduler() -> BackgroundScheduler:
    global _scheduler
    _scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(engine=_db_engine)},
        executors={"default": ThreadPoolExecutor(max_workers=4)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120},
    )
    _scheduler.start()
    logger.info("APScheduler started")
    return _scheduler


def shutdown_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")

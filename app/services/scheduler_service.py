import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialised — call init_scheduler() first")
    return _scheduler


def init_scheduler() -> BackgroundScheduler:
    """
    Start APScheduler with SQLAlchemy persistence where available, falling
    back to an in-memory store if the database is unreachable at boot time.

    This prevents a slow/failed DB connection from blocking the process
    startup on cold-start environments (e.g. Render free tier with a remote
    Supabase database in a different region).
    """
    global _scheduler

    try:
        from app.database import engine as _db_engine
        jobstore = SQLAlchemyJobStore(engine=_db_engine)
        # Probe the connection so we fail fast rather than hang
        with _db_engine.connect():
            pass
        jobstores = {"default": jobstore}
        logger.info("APScheduler using SQLAlchemy job store")
    except Exception as exc:
        logger.warning(
            "DB unavailable at startup — APScheduler falling back to MemoryJobStore",
            extra={"error": str(exc)},
        )
        jobstores = {"default": MemoryJobStore()}

    _scheduler = BackgroundScheduler(
        jobstores=jobstores,
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

import logging
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.jobs.campaign_job import run_campaign_job
from app.schemas.campaign import (
    CampaignAnalytics,
    CampaignCreate,
    CampaignMessageOut,
    CampaignOut,
)
from app.services.campaign_service import CampaignService
from app.services.scheduler_service import get_scheduler

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])
logger = logging.getLogger(__name__)

_svc = CampaignService()


@router.post("/", response_model=CampaignOut, status_code=201, summary="Create a new campaign")
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    campaign = _svc.create(payload, db)

    if campaign.status.value == "scheduled" and campaign.scheduled_at:
        get_scheduler().add_job(
            run_campaign_job,
            trigger="date",
            run_date=campaign.scheduled_at,
            args=[campaign.id],
            id=f"campaign_{campaign.id}",
            replace_existing=True,
        )
        logger.info(
            "Campaign scheduled",
            extra={"campaign_id": campaign.id, "run_date": str(campaign.scheduled_at)},
        )

    return campaign


@router.get("/", response_model=list[CampaignOut], summary="List all campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    return _svc.get_all(db)


@router.get("/{campaign_id}", response_model=CampaignOut, summary="Get campaign by ID")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    return _svc.get_by_id(campaign_id, db)


@router.post(
    "/{campaign_id}/start",
    response_model=CampaignOut,
    summary="Start a campaign immediately (runs in background)",
)
def start_campaign(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    campaign = _svc.start(campaign_id, db)

    # Remove any previously scheduled APScheduler job for this campaign
    try:
        get_scheduler().remove_job(f"campaign_{campaign_id}")
    except Exception:
        pass

    background_tasks.add_task(run_campaign_job, campaign_id)
    return campaign


@router.post(
    "/{campaign_id}/cancel",
    response_model=CampaignOut,
    summary="Cancel a draft, scheduled, or running campaign",
)
def cancel_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = _svc.cancel(campaign_id, db)
    try:
        get_scheduler().remove_job(f"campaign_{campaign_id}")
    except Exception:
        pass
    return campaign


@router.get(
    "/{campaign_id}/messages",
    response_model=list[CampaignMessageOut],
    summary="List messages for a campaign",
)
def list_messages(
    campaign_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return _svc.get_messages(campaign_id, db, skip=skip, limit=limit)


@router.get(
    "/{campaign_id}/analytics",
    response_model=CampaignAnalytics,
    summary="Get delivery analytics for a campaign",
)
def get_analytics(campaign_id: int, db: Session = Depends(get_db)):
    return _svc.get_analytics(campaign_id, db)

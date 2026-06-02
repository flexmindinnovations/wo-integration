import logging
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.campaign import Campaign, CampaignStatus
from app.models.campaign_message import CampaignMessage, DeliveryStatus
from app.models.contact import Contact
from app.schemas.campaign import CampaignCreate, CampaignAnalytics

logger = logging.getLogger(__name__)


class CampaignService:
    def create(self, payload: CampaignCreate, db: Session) -> Campaign:
        now = datetime.utcnow()
        status = (
            CampaignStatus.scheduled
            if payload.scheduled_at and payload.scheduled_at > now
            else CampaignStatus.draft
        )
        campaign = Campaign(
            name=payload.name,
            topic=payload.topic,
            template_name=payload.template_name,
            template_language=payload.template_language,
            template_components=payload.template_components,
            status=status,
            scheduled_at=payload.scheduled_at,
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        logger.info("Campaign created", extra={"campaign_id": campaign.id, "campaign_name": campaign.name})
        return campaign

    def get_all(self, db: Session) -> list[Campaign]:
        return db.query(Campaign).order_by(Campaign.created_at.desc()).all()

    def get_by_id(self, campaign_id: int, db: Session) -> Campaign:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
        return campaign

    def start(self, campaign_id: int, db: Session) -> Campaign:
        campaign = self.get_by_id(campaign_id, db)

        if campaign.status == CampaignStatus.running:
            raise HTTPException(status_code=409, detail="Campaign is already running")
        if campaign.status in (CampaignStatus.completed, CampaignStatus.failed):
            raise HTTPException(
                status_code=409, detail=f"Cannot restart a {campaign.status.value} campaign"
            )

        contacts = db.query(Contact).all()
        if not contacts:
            raise HTTPException(
                status_code=422,
                detail="No contacts in database. Run POST /contacts/sync first.",
            )

        # Create a pending CampaignMessage for each contact (idempotent)
        existing_ids = {
            row[0]
            for row in db.query(CampaignMessage.contact_id)
            .filter(CampaignMessage.campaign_id == campaign_id)
            .all()
        }
        new_msgs = [
            CampaignMessage(
                campaign_id=campaign_id,
                contact_id=c.id,
                delivery_status=DeliveryStatus.pending,
            )
            for c in contacts
            if c.id not in existing_ids
        ]
        if new_msgs:
            db.bulk_save_objects(new_msgs)

        campaign.status = CampaignStatus.running
        campaign.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(campaign)

        logger.info(
            "Campaign started",
            extra={"campaign_id": campaign_id, "contacts": len(contacts)},
        )
        return campaign

    def cancel(self, campaign_id: int, db: Session) -> Campaign:
        campaign = self.get_by_id(campaign_id, db)
        if campaign.status in (CampaignStatus.completed, CampaignStatus.failed):
            raise HTTPException(
                status_code=409, detail=f"Cannot cancel a {campaign.status.value} campaign"
            )
        campaign.status = CampaignStatus.failed
        campaign.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(campaign)
        logger.info("Campaign cancelled", extra={"campaign_id": campaign_id})
        return campaign

    def get_messages(
        self, campaign_id: int, db: Session, skip: int = 0, limit: int = 100
    ) -> list[CampaignMessage]:
        self.get_by_id(campaign_id, db)
        return (
            db.query(CampaignMessage)
            .filter(CampaignMessage.campaign_id == campaign_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_analytics(self, campaign_id: int, db: Session) -> CampaignAnalytics:
        campaign = self.get_by_id(campaign_id, db)

        rows = (
            db.query(CampaignMessage.delivery_status, func.count(CampaignMessage.id))
            .filter(CampaignMessage.campaign_id == campaign_id)
            .group_by(CampaignMessage.delivery_status)
            .all()
        )
        stats: dict[str, int] = {status.value: count for status, count in rows}

        total = sum(stats.values())
        pending = stats.get("pending", 0)
        sent = stats.get("sent", 0)
        delivered = stats.get("delivered", 0)
        read = stats.get("read", 0)
        failed = stats.get("failed", 0)

        # "delivered" in analytics means confirmed received (delivered + read)
        confirmed_delivered = delivered + read

        return CampaignAnalytics(
            campaign_id=campaign_id,
            campaign_name=campaign.name,
            status=campaign.status,
            total_contacts=total,
            pending=pending,
            sent=sent + confirmed_delivered,  # left our system
            delivered=confirmed_delivered,
            read=read,
            failed=failed,
            delivery_rate=round(confirmed_delivered / total, 4) if total else 0.0,
            read_rate=round(read / total, 4) if total else 0.0,
        )

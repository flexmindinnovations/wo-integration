import json
import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.models.campaign_message import CampaignMessage, DeliveryStatus
from app.models.contact import Contact
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


def run_campaign_job(campaign_id: int) -> None:
    """
    APScheduler / BackgroundTasks entry point.
    Opens its own DB session so it's safe to call from any thread.
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            logger.error("Campaign not found", extra={"campaign_id": campaign_id})
            return

        # Scheduled campaigns need to be prepared before execution
        if campaign.status == CampaignStatus.scheduled:
            from app.services.campaign_service import CampaignService
            try:
                CampaignService().start(campaign_id, db)
                db.refresh(campaign)
            except Exception as exc:
                logger.error(
                    "Failed to prepare scheduled campaign",
                    extra={"campaign_id": campaign_id, "error": str(exc)},
                )
                return

        _execute(campaign_id, db)
    except Exception:
        logger.exception("Unhandled error in campaign job", extra={"campaign_id": campaign_id})
    finally:
        db.close()


def _execute(campaign_id: int, db: Session) -> None:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign or campaign.status != CampaignStatus.running:
        logger.warning(
            "Campaign not in running state — aborting",
            extra={"campaign_id": campaign_id},
        )
        return

    logger.info("Campaign job started", extra={"campaign_id": campaign_id, "campaign_name": campaign.name})

    whatsapp = WhatsAppService()
    batch_size = settings.CAMPAIGN_BATCH_SIZE
    delay = settings.MESSAGE_DELAY_SECONDS

    pending = (
        db.query(CampaignMessage)
        .filter(
            CampaignMessage.campaign_id == campaign_id,
            CampaignMessage.delivery_status == DeliveryStatus.pending,
        )
        .all()
    )

    total = len(pending)
    sent_count = failed_count = 0

    for batch_start in range(0, total, batch_size):
        batch = pending[batch_start : batch_start + batch_size]

        for msg in batch:
            contact = db.query(Contact).filter(Contact.id == msg.contact_id).first()
            if not contact:
                msg.delivery_status = DeliveryStatus.failed
                msg.error_message = "Contact record not found"
                db.commit()
                failed_count += 1
                continue

            if _send_with_retry(whatsapp, campaign, contact, msg, db):
                sent_count += 1
            else:
                failed_count += 1

            if delay > 0:
                time.sleep(delay)

        logger.info(
            "Batch processed",
            extra={
                "campaign_id": campaign_id,
                "batch": batch_start // batch_size + 1,
                "sent_so_far": sent_count,
                "failed_so_far": failed_count,
            },
        )

    campaign.status = (
        CampaignStatus.failed if (total == 0 or failed_count == total)
        else CampaignStatus.completed
    )
    campaign.updated_at = datetime.utcnow()
    db.commit()

    logger.info(
        "Campaign job completed",
        extra={
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "total": total,
            "sent": sent_count,
            "failed": failed_count,
        },
    )


def _send_with_retry(
    whatsapp: WhatsAppService,
    campaign: Campaign,
    contact: Contact,
    msg: CampaignMessage,
    db: Session,
) -> bool:
    max_retries = settings.MAX_RETRY_ATTEMPTS
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            # AI extension point: replace _build_components() with an AI service
            # that uses campaign.topic to generate personalised message variables.
            components = _build_components(campaign, contact)
            result = whatsapp.send_template(
                phone=contact.phone,
                template_name=campaign.template_name,
                language_code=campaign.template_language or "en",
                components=components,
            )
            wa_msg_id = (result.get("messages") or [{}])[0].get("id")
            msg.whatsapp_message_id = wa_msg_id
            msg.delivery_status = DeliveryStatus.sent
            msg.sent_at = datetime.utcnow()
            msg.retry_count = attempt
            msg.error_message = None
            db.commit()
            logger.info(
                "Message sent",
                extra={"phone": contact.phone, "wamid": wa_msg_id, "attempt": attempt},
            )
            return True
        except Exception as exc:
            last_error = exc
            msg.retry_count = attempt
            db.commit()
            logger.warning(
                "Send attempt failed",
                extra={
                    "phone": contact.phone,
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "error": str(exc),
                },
            )
            if attempt < max_retries:
                time.sleep(2**attempt)  # exponential backoff: 2 s, 4 s

    msg.delivery_status = DeliveryStatus.failed
    msg.error_message = str(last_error)
    db.commit()
    logger.error(
        "Message failed after all retries",
        extra={"phone": contact.phone, "attempts": max_retries, "error": str(last_error)},
    )
    return False


def _build_components(campaign: Campaign, contact: Contact) -> list[dict] | None:
    """
    Build WhatsApp template body components.

    If the campaign has stored template_components, substitute contact-specific
    placeholders and return them. Supported placeholders:
        {{contact_name}}   → contact's full name
        {{contact_phone}}  → contact's phone number
        {{contact_email}}  → contact's email (empty string if none)

    If no components are stored (e.g. templates with no variables like hello_world),
    returns None so the message is sent without body parameters.

    AI extension point: replace this function with an AI service call that uses
    campaign.topic to dynamically generate the parameter values per contact.
    """
    if not campaign.template_components:
        logger.warning(
            "Campaign has no template components configured",
            extra={"campaign_id": campaign.id, "template": campaign.template_name},
        )
        return None

    # Substitute contact-specific placeholders with live data
    raw = json.dumps(campaign.template_components)
    raw = raw.replace("{{contact_name}}", contact.name)
    raw = raw.replace("{{contact_phone}}", contact.phone)
    raw = raw.replace("{{contact_email}}", contact.email or "")
    return json.loads(raw)

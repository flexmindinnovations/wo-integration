import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.campaign_message import CampaignMessage, DeliveryStatus

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger(__name__)


@router.get("/whatsapp", summary="WhatsApp webhook verification handshake")
def verify_webhook(request: Request) -> Response:
    """
    WhatsApp Cloud API calls this endpoint to verify the webhook URL.
    Responds with hub.challenge when the verify token matches.
    """
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/whatsapp", summary="Receive WhatsApp status and message events")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Processes incoming webhook events from WhatsApp Cloud API:

    - **Delivery status updates** (sent / delivered / read / failed) → update CampaignMessage records.
    - **Incoming messages** → AI extension point (not yet implemented).

    Always returns HTTP 200 so WhatsApp does not retry the delivery.
    """
    try:
        payload = await request.json()
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                for status_event in value.get("statuses", []):
                    _process_status_update(status_event, db)

                # AI extension point: incoming customer messages
                for message in value.get("messages", []):
                    _handle_incoming_message(message)

    except Exception:
        logger.exception("Error processing WhatsApp webhook")
        # Return 200 regardless to prevent WhatsApp from retrying

    return {"status": "ok"}


def _process_status_update(event: dict, db: Session) -> None:
    """Map a WhatsApp status event to the corresponding CampaignMessage row."""
    wamid: str | None = event.get("id")
    raw_status: str | None = event.get("status")

    _status_map = {
        "sent": DeliveryStatus.sent,
        "delivered": DeliveryStatus.delivered,
        "read": DeliveryStatus.read,
        "failed": DeliveryStatus.failed,
    }
    status = _status_map.get(raw_status or "")
    if not wamid or not status:
        return

    msg = (
        db.query(CampaignMessage)
        .filter(CampaignMessage.whatsapp_message_id == wamid)
        .first()
    )
    if not msg:
        logger.debug("No message record for wamid", extra={"wamid": wamid})
        return

    msg.delivery_status = status
    if status == DeliveryStatus.failed:
        errors = event.get("errors", [])
        msg.error_message = errors[0].get("message") if errors else "Delivery failed"

    db.commit()
    logger.info(
        "Delivery status updated",
        extra={"wamid": wamid, "status": raw_status},
    )


def _handle_incoming_message(message: dict) -> None:
    """
    Extension point for AI-powered reply handling.

    Future implementation:
        1. Extract text from `message["text"]["body"]`
        2. Send to OpenAI / Claude with conversation context
        3. Call WhatsAppService().send_text(phone, ai_reply)
    """
    logger.info(
        "Incoming WhatsApp message — AI handler not yet implemented",
        extra={"sender": message.get("from"), "msg_type": message.get("type")},
    )

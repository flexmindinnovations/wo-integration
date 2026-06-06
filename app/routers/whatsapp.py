import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.campaign_message import CampaignMessage, DeliveryStatus
from app.models.conversation_message import ConversationMessage, MessageRole
from app.models.contact import Contact
from app.services.ai_service import AiService
from app.services.whatsapp_service import WhatsAppService
from app.services.odoo_service import OdooService

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
                    _handle_incoming_message(message, db)

    except Exception:
        logger.exception("Error processing WhatsApp webhook")
        # Return 200 regardless to prevent WhatsApp from retrying

    return {"status": "ok"}


def _send_invoice_pdfs(phone: str, invoices: list[dict], db: Session) -> None:
    """
    Send invoice PDFs to the user.
    Attempts to fetch from Odoo first, then falls back to generated PDF.
    """
    try:
        from app.services.odoo_service import OdooService

        odoo = OdooService()
        whatsapp = WhatsAppService()

        sent_count = 0
        for inv in invoices[:3]:  # Limit to 3 PDFs to avoid spam
            try:
                invoice_id = inv.get("id")
                invoice_name = inv.get("name", "Invoice")
                if not invoice_id:
                    continue

                logger.info(
                    "Starting invoice PDF fetch and send",
                    extra={"phone": phone, "invoice_id": invoice_id, "invoice_name": invoice_name}
                )

                pdf_bytes = None
                pdf_source = None

                # Try to fetch PDF from Odoo first
                try:
                    pdf_bytes = odoo.get_invoice_pdf(invoice_id)
                    pdf_source = "odoo"
                    logger.info(
                        "Invoice PDF fetched from Odoo",
                        extra={"phone": phone, "invoice_id": invoice_id, "pdf_size": len(pdf_bytes)}
                    )
                except Exception as odoo_error:
                    logger.warning(
                        "Failed to fetch from Odoo, trying PDF generation fallback",
                        extra={"phone": phone, "invoice_id": invoice_id, "error": str(odoo_error)}
                    )

                    # Fallback: Generate PDF from invoice data
                    try:
                        pdf_bytes = odoo.generate_invoice_pdf(inv)
                        pdf_source = "generated"
                        logger.info(
                            "Invoice PDF generated as fallback",
                            extra={"phone": phone, "invoice_id": invoice_id, "pdf_size": len(pdf_bytes)}
                        )
                    except Exception as gen_error:
                        logger.error(
                            "Failed to generate PDF fallback",
                            extra={"phone": phone, "invoice_id": invoice_id, "error": str(gen_error)}
                        )
                        continue

                if not pdf_bytes:
                    logger.warning(
                        "No PDF bytes available",
                        extra={"phone": phone, "invoice_id": invoice_id}
                    )
                    continue

                # Upload to Meta and get media ID
                upload_filename = f"{invoice_name}.pdf"
                media_id = whatsapp.upload_media(
                    pdf_bytes,
                    upload_filename,
                    "application/pdf"
                )
                logger.info(
                    "Invoice PDF uploaded to Meta",
                    extra={"phone": phone, "invoice_id": invoice_id, "media_id": media_id, "source": pdf_source}
                )

                # Send the document using media ID with proper filename
                whatsapp.send_document_by_id(phone, media_id, invoice_name)
                logger.info(
                    "Invoice PDF sent successfully",
                    extra={"phone": phone, "invoice_id": invoice_id, "invoice_name": invoice_name, "source": pdf_source}
                )
                sent_count += 1

            except Exception as e:
                logger.warning(
                    "Failed to send invoice PDF",
                    extra={"phone": phone, "invoice_id": inv.get("id"), "error": str(e)}
                )
                continue

        if sent_count > 0:
            logger.info(
                "Invoice PDFs sent",
                extra={"phone": phone, "sent_count": sent_count}
            )

    except Exception as e:
        logger.exception(
            "Error in invoice PDF handler",
            extra={"phone": phone, "error": str(e)}
        )


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


def _handle_incoming_message(message: dict, db: Session) -> None:
    """
    Handle an inbound WhatsApp message:
      1. Only process text messages; log and skip everything else.
      2. Deduplicate by wamid to handle webhook retries.
      3. Persist user message → generate AI reply → persist reply → send reply.
      4. Never raise — the caller must always return HTTP 200.
    """
    msg_type: str = message.get("type", "")
    phone: str = message.get("from", "")
    wamid: str = message.get("id", "")

    if msg_type != "text":
        logger.info(
            "Non-text message received — skipping",
            extra={"phone": phone, "type": msg_type},
        )
        return

    text_body: str = (message.get("text") or {}).get("body", "").strip()
    if not text_body:
        logger.warning("Text message with empty body", extra={"phone": phone, "wamid": wamid})
        return

    try:
        # Deduplication
        if wamid:
            existing = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.wamid == wamid)
                .first()
            )
            if existing:
                logger.info(
                    "Duplicate message — already processed",
                    extra={"phone": phone, "wamid": wamid},
                )
                return

        # Persist user message
        user_msg = ConversationMessage(
            contact_phone=phone,
            role=MessageRole.user,
            content=text_body,
            wamid=wamid or None,
        )
        db.add(user_msg)
        db.commit()
        db.refresh(user_msg)

        # Fetch contact and Odoo context for AI reply
        from app.models.contact import Contact
        contact = db.query(Contact).filter(Contact.phone == phone).first()
        odoo_context = None

        if contact and contact.odoo_partner_id:
            try:
                from app.services.odoo_service import OdooService
                odoo = OdooService()
                odoo_context = odoo.fetch_customer_context(contact.odoo_partner_id)
            except Exception as e:
                logger.warning(
                    "Failed to fetch Odoo context — proceeding with generic reply",
                    extra={"phone": phone, "partner_id": contact.odoo_partner_id, "error": str(e)},
                )
        else:
            logger.warning(
                "Contact not linked to Odoo or contact not found",
                extra={"phone": phone, "contact_found": contact is not None, "has_partner_id": contact.odoo_partner_id if contact else None},
            )

        # Generate AI reply with context
        ai_reply = AiService().generate_reply_with_context(
            phone, db,
            contact=contact,
            odoo_context=odoo_context
        )

        # Persist assistant message
        assistant_msg = ConversationMessage(
            contact_phone=phone,
            role=MessageRole.assistant,
            content=ai_reply,
            wamid=None,
        )
        db.add(assistant_msg)
        db.commit()

        # Send reply via WhatsApp
        WhatsAppService().send_text(phone, ai_reply)
        logger.info("AI reply sent", extra={"phone": phone})

        # If user asked about invoices and we have invoice data, send PDF
        user_msg_lower = text_body.lower()
        has_invoices = odoo_context and odoo_context.get("invoices")
        is_invoice_request = any(
            keyword in user_msg_lower
            for keyword in ["invoice", "bill", "pdf", "document", "payment"]
        )

        logger.info(
            "Checking if should send invoice PDFs",
            extra={
                "phone": phone,
                "is_invoice_request": is_invoice_request,
                "has_invoices": bool(has_invoices),
                "invoice_count": len(odoo_context.get("invoices", [])) if has_invoices else 0,
                "has_contact": contact is not None,
                "has_odoo_partner": contact.odoo_partner_id if contact else None,
            }
        )

        if is_invoice_request and has_invoices and contact and contact.odoo_partner_id:
            logger.info("Sending invoice PDFs", extra={"phone": phone, "count": len(odoo_context.get("invoices", []))})
            _send_invoice_pdfs(phone, odoo_context.get("invoices", []), db)
        else:
            logger.info(
                "Not sending PDFs (conditions not met)",
                extra={
                    "phone": phone,
                    "is_invoice_request": is_invoice_request,
                    "has_invoices": bool(has_invoices),
                    "has_contact": contact is not None,
                }
            )

    except Exception:
        logger.exception(
            "Error in AI message handler — suppressing to preserve 200 response",
            extra={"phone": phone, "wamid": wamid},
        )
        try:
            db.rollback()
        except Exception:
            pass


@router.get("/debug/invoice/{phone}", summary="Debug invoice fetch for a phone number")
def debug_invoice_fetch(phone: str, db: Session = Depends(get_db)):
    """
    Diagnostic endpoint to debug why invoices aren't being fetched.

    Returns:
    - Contact details if found
    - Odoo partner ID
    - Fetched invoices
    - Any errors encountered
    """
    try:
        contact = db.query(Contact).filter(Contact.phone == phone).first()

        if not contact:
            return {
                "phone": phone,
                "status": "contact_not_found",
                "message": "Contact with this phone number not found in database"
            }

        response = {
            "phone": phone,
            "contact_found": True,
            "contact_id": contact.id,
            "contact_name": contact.name,
            "odoo_partner_id": contact.odoo_partner_id,
        }

        if not contact.odoo_partner_id:
            return {
                **response,
                "status": "no_odoo_link",
                "message": "Contact is not linked to any Odoo partner. Run contact sync first."
            }

        # Try to fetch Odoo context
        try:
            odoo = OdooService()
            context = odoo.fetch_customer_context(contact.odoo_partner_id)

            return {
                **response,
                "status": "success",
                "odoo_context": {
                    "access_success": context.get("access_success"),
                    "company_name": context.get("company_name"),
                    "invoice_count": len(context.get("invoices", [])),
                    "invoices": [
                        {
                            "name": inv.get("name"),
                            "amount": inv.get("amount_total"),
                            "due_date": inv.get("due_date"),
                            "payment_state": inv.get("payment_state")
                        }
                        for inv in context.get("invoices", [])
                    ],
                    "order_count": len(context.get("orders", [])),
                    "payment_count": len(context.get("payments", [])),
                }
            }
        except Exception as e:
            return {
                **response,
                "status": "odoo_error",
                "message": f"Failed to fetch Odoo context: {str(e)}"
            }

    except Exception as e:
        logger.exception("Error in debug endpoint", extra={"phone": phone})
        return {
            "status": "error",
            "message": f"Unexpected error: {str(e)}"
        }

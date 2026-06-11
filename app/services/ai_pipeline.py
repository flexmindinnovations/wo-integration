import logging
from app.database import SessionLocal
from app.models.conversation_message import ConversationMessage, MessageRole
from app.models.contact import Contact
from app.services.ai_service import AiService
from app.services.whatsapp_service import WhatsAppService
from app.services.odoo_service import OdooService
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

# Any of these means the message is about invoices/billing (used to enrich AI context)
_INVOICE_KEYWORDS = {"invoice", "bill", "pdf", "document", "payment"}

# User must include one of these to actually trigger a PDF send
_PDF_SEND_KEYWORDS = {"pdf", "send", "share", "document", "attach", "download", "view"}


def serialize_message(msg: ConversationMessage) -> dict:
    return {
        "id": msg.id,
        "contact_phone": msg.contact_phone,
        "role": msg.role.value,
        "content": msg.content,
        "wamid": msg.wamid,
        "created_at": msg.created_at.isoformat() + "Z",  # UTC — browser converts to local time
    }


async def process_ai_reply(phone: str, text_body: str) -> None:
    """
    Background task: generate AI reply → broadcast → send via WhatsApp.
    Also sends invoice PDFs when the user asks about invoices and saves each
    PDF as a ConversationMessage so it appears in the web UI.

    AI failures are fully isolated — PDFs are sent regardless.
    When the AI quota is exhausted but invoices are available, a structured
    invoice summary message is used instead of the generic fallback.
    """
    db = SessionLocal()
    try:
        # Broadcast the user message that was already persisted
        user_msg = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_phone == phone,
                ConversationMessage.role == MessageRole.user,
            )
            .order_by(ConversationMessage.created_at.desc())
            .first()
        )
        if user_msg:
            await manager.broadcast({"type": "new_message", "message": serialize_message(user_msg)})

        contact = db.query(Contact).filter(Contact.phone == phone).first()
        odoo_context = None

        if contact and contact.odoo_partner_id:
            try:
                odoo_context = OdooService().fetch_customer_context(contact.odoo_partner_id)
            except Exception as e:
                logger.warning("Failed to fetch Odoo context", extra={"phone": phone, "error": str(e)})
        else:
            logger.warning("Contact not linked to Odoo or not found", extra={"phone": phone})

        query = text_body.lower()
        is_invoice_request = any(kw in query for kw in _INVOICE_KEYWORDS)
        # PDF send requires explicit intent — "how many" / "just count" should NOT trigger
        should_send_pdf = is_invoice_request and any(kw in query for kw in _PDF_SEND_KEYWORDS)
        invoices = odoo_context.get("invoices", []) if odoo_context else []
        has_invoices = bool(invoices)

        # ── AI reply ──────────────────────────────────────────────────────────
        ai_reply, is_fallback = _safe_generate_reply(phone, db, contact, odoo_context)

        if is_fallback:
            if is_invoice_request and has_invoices:
                ai_reply = _build_invoice_reply(contact, invoices[:3], text_body)
            else:
                ai_reply = "Sorry, I encountered an error. Please try again shortly."

        assistant_msg = ConversationMessage(
            contact_phone=phone,
            role=MessageRole.assistant,
            content=ai_reply,
            wamid=None,
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        # Broadcast to UI before WhatsApp send so chat updates even if delivery fails
        await manager.broadcast({"type": "new_message", "message": serialize_message(assistant_msg)})

        try:
            WhatsAppService().send_text(phone, ai_reply)
            logger.info("AI reply sent via WhatsApp", extra={"phone": phone})
        except Exception as wa_err:
            logger.warning("WhatsApp send failed for AI reply", extra={"phone": phone, "error": str(wa_err)})

        # ── Invoice PDFs — only when user explicitly asked for them ──────────
        if should_send_pdf and has_invoices and contact and contact.odoo_partner_id:
            await _send_invoices_and_record(phone, invoices, db)

    except Exception:
        logger.exception("Error in AI reply pipeline", extra={"phone": phone})
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _safe_generate_reply(phone, db, contact, odoo_context) -> tuple[str, bool]:
    """
    Generate AI reply. Returns (text, is_fallback).
    is_fallback=True means the AI model failed and the caller should decide
    what message to show.
    """
    try:
        reply = AiService().generate_reply_with_context(
            phone, db, contact=contact, odoo_context=odoo_context
        )
        return reply, False
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            logger.warning("Gemini quota exhausted — using fallback reply", extra={"phone": phone})
        else:
            logger.error("AI reply failed", extra={"phone": phone, "error": err})
        return "", True


def _build_invoice_reply(contact, invoices: list, user_query: str = "") -> str:
    """
    Structured fallback used only when the AI model is unavailable.
    Returns a neutral account summary — the AI normally handles intent.
    PDF line is added only if the user explicitly asked for one.
    """
    first_name = contact.name.split()[0] if (contact and contact.name) else "there"
    count = len(invoices)
    noun = "invoice" if count == 1 else "invoices"

    lines = []
    for inv in invoices:
        name   = inv.get("name", "Invoice")
        amount = inv.get("amount_total", 0)
        date   = inv.get("invoice_date") or inv.get("invoice_date_due") or "N/A"
        status = inv.get("payment_state", "unknown").replace("_", " ")
        lines.append(f"• *{name}* — ₹{amount:,.2f} (Date: {date}, Status: {status})")

    body = (
        f"Hi {first_name}, here's a summary of your account:\n\n"
        f"You have *{count}* outstanding {noun}:\n"
        + "\n".join(lines)
    )

    wants_pdf = any(kw in user_query.lower() for kw in _PDF_SEND_KEYWORDS)
    if wants_pdf:
        inv_names = ", ".join(f"*{inv.get('name', 'Invoice')}*" for inv in invoices)
        pdf_line = (
            f"The PDF for invoice {inv_names} is being sent to you now."
            if count == 1
            else f"The PDFs for {inv_names} are being sent to you now."
        )
        body += f"\n\n{pdf_line}"

    return body


async def _send_invoices_and_record(phone: str, invoices: list, db) -> None:
    """
    Send up to 3 invoice PDFs via WhatsApp, then save each as a ConversationMessage
    and broadcast to the web UI so it appears in the chat.
    """
    from app.routers.whatsapp import _send_invoice_pdfs

    invoices_to_send = invoices[:3]

    try:
        _send_invoice_pdfs(phone, invoices_to_send, db)
    except Exception as e:
        logger.warning("Invoice PDF sending failed", extra={"phone": phone, "error": str(e)})

    # Save a document message for each invoice so the web UI shows it.
    # Format: "📎 {id}:{name}.pdf" — the UI extracts the ID to build a download link.
    doc_msgs = []
    for inv in invoices_to_send:
        inv_id = inv.get("id", "")
        inv_name = inv.get("name", "Invoice")
        doc_msg = ConversationMessage(
            contact_phone=phone,
            role=MessageRole.assistant,
            content=f"📎 {inv_id}:{inv_name}.pdf",
            wamid=None,
        )
        db.add(doc_msg)
        doc_msgs.append(doc_msg)

    db.commit()
    for doc_msg in doc_msgs:
        db.refresh(doc_msg)
        await manager.broadcast({"type": "new_message", "message": serialize_message(doc_msg)})
        logger.info("PDF message broadcast to UI", extra={"phone": phone, "doc": doc_msg.content})

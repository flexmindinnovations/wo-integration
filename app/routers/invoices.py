import logging
from typing import List, Optional, Any, Dict
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.contact import Contact
from app.schemas.invoice import InvoiceCreate, InvoiceOut, InvoiceLineCreate
from app.services.odoo_service import OdooService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.get(
    "/",
    response_model=List[InvoiceOut],
    summary="List all invoices from Odoo",
)
def list_invoices(skip: int = 0, limit: int = 100):
    """Fetch all customer invoices directly from Odoo."""
    try:
        odoo = OdooService()
        return odoo.list_all_invoices(limit=limit, offset=skip)
    except Exception as e:
        logger.error("Failed to list invoices", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Odoo error listing invoices: {str(e)}")


@router.post(
    "/",
    response_model=int,
    status_code=201,
    summary="Create a new draft invoice in Odoo",
)
def create_invoice(payload: InvoiceCreate):
    """
    Create a new draft customer invoice in Odoo.
    Returns the created Odoo invoice ID.
    """
    try:
        odoo = OdooService()
        lines_data = [line.model_dump() for line in payload.lines]
        invoice_id = odoo.create_invoice(
            partner_id=payload.partner_id,
            invoice_date=payload.invoice_date,
            lines=lines_data
        )
        return invoice_id
    except Exception as e:
        logger.error("Failed to create invoice", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Odoo error creating invoice: {str(e)}")


@router.get(
    "/{invoice_id}",
    response_model=InvoiceOut,
    summary="Get invoice details including lines from Odoo",
)
def get_invoice(invoice_id: int):
    """Get complete invoice details and invoice lines from Odoo."""
    try:
        odoo = OdooService()
        return odoo.get_invoice(invoice_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to fetch invoice {invoice_id}", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{invoice_id}/post",
    summary="Post/Confirm a draft invoice in Odoo",
)
def post_invoice(invoice_id: int):
    """Confirm/post a draft invoice in Odoo (updates state to posted)."""
    try:
        odoo = OdooService()
        success = odoo.post_invoice(invoice_id)
        return {"status": "success" if success else "failed"}
    except Exception as e:
        logger.error(f"Failed to post invoice {invoice_id}", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


class SendInvoiceWhatsAppPayload(BaseModel):
    template_name: str = "invoice"
    template_language: str = "en"
    company_name: str = "Flexmind Innovations"
    invoice_url: Optional[str] = None


@router.post(
    "/{invoice_id}/send-whatsapp",
    summary="Send invoice details to partner via WhatsApp template",
)
def send_invoice_whatsapp(
    invoice_id: int,
    payload: SendInvoiceWhatsAppPayload,
    db: Session = Depends(get_db)
):
    """
    Fetch the invoice and customer partner phone number from Odoo,
    then send an approved WhatsApp invoice template notification.
    """
    try:
        odoo = OdooService()
        invoice = odoo.get_invoice(invoice_id)
        
        partner_relation = invoice.get("partner_id")
        if not partner_relation or not isinstance(partner_relation, (list, tuple)):
            raise HTTPException(status_code=422, detail="Invoice does not have a valid partner linked")
            
        partner_id = partner_relation[0]
        partner_name = partner_relation[1]
        
        # Look up phone number for the partner in local database or query Odoo
        contact = db.query(Contact).filter(Contact.odoo_partner_id == partner_id).first()
        phone = None
        if contact:
            phone = contact.phone
        else:
            # Query Odoo res.partner
            partners = odoo._execute("res.partner", "read", [[partner_id]], {"fields": ["phone"]})
            if partners and partners[0].get("phone"):
                # Normalize phone
                raw_phone = partners[0]["phone"]
                phone = "".join(ch for ch in raw_phone if ch.isdigit())
                
        if not phone:
            raise HTTPException(
                status_code=400,
                detail=f"Could not find a phone number for partner {partner_name} (ID {partner_id})"
            )
            
        # Format variables for template components
        # Template is `invoice` (6 params): Hello {{1}}, invoice {{2}} from {{3}} has been generated for {{4}} {{5}}. You can view or download your invoice here: {{6}}
        invoice_number = invoice.get("name", f"INV-{invoice_id}")
        amount_str = f"{invoice.get('amount_total', 0.0):.2f}"
        currency = "INR"
        download_url = payload.invoice_url or f"{settings.ODOO_URL}/my/invoices/{invoice_id}"
        
        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": partner_name},
                    {"type": "text", "text": invoice_number},
                    {"type": "text", "text": payload.company_name},
                    {"type": "text", "text": currency},
                    {"type": "text", "text": amount_str},
                    {"type": "text", "text": download_url}
                ]
            }
        ]
        
        whatsapp = WhatsAppService()
        result = whatsapp.send_template(
            phone=phone,
            template_name=payload.template_name,
            language_code=payload.template_language,
            components=components
        )
        
        wa_msg_id = (result.get("messages") or [{}])[0].get("id")
        
        # Log the message record locally
        from app.models.campaign_message import CampaignMessage, DeliveryStatus
        msg = CampaignMessage(
            campaign_id=9999, # Chat/Direct invoice log tag
            contact_id=contact.id if contact else 0,
            whatsapp_message_id=wa_msg_id,
            delivery_status=DeliveryStatus.sent,
            sent_at=None # Sent/Webhook will update it
        )
        if contact:
            db.add(msg)
            db.commit()
            
        return {"status": "success", "whatsapp_message_id": wa_msg_id}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Failed to dispatch WhatsApp invoice notification", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"WhatsApp error: {str(e)}")

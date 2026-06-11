import logging
import xmlrpc.client
import requests
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict, List
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch, mm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

from app.config import settings
from app.models.contact import Contact
from app.constants import (
    OdooModels, OdooFieldsPartner, OdooFieldsInvoice, OdooFieldsInvoiceLine,
    OdooFieldsSaleOrder, OdooFieldsPayment, OdooMoveTypes, OdooInvoiceStates,
    OdooPaymentStates, OdooActions, OdooReports, ApiTimeouts, ApiDefaults,
    OrderByField, InvoiceDefaults, ContactSync, CurrencySymbols, LogMessages,
    Pagination, PhoneFormatting
)

logger = logging.getLogger(__name__)

# Check if reportlab is available (for runtime checking only)
try:
    import reportlab.lib.pagesizes
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.warning("reportlab not installed - PDF generation fallback will not be available")


def _normalize_phone(raw: str) -> str:
    """Strip all non-digit characters from a phone number."""
    return "".join(ch for ch in raw if ch.isdigit())


class OdooService:
    def __init__(self) -> None:
        password = settings.ODOO_PASSWORD or settings.ODOO_API_KEY
        if not password:
            raise ValueError("Either ODOO_PASSWORD or ODOO_API_KEY must be set in .env")

        # Normalize URL: ensure HTTPS and clean up
        odoo_url = settings.ODOO_URL.strip()

        # Auto-upgrade HTTP to HTTPS
        if odoo_url.startswith('http://'):
            odoo_url = odoo_url.replace('http://', 'https://', 1)
        elif not odoo_url.startswith('https://'):
            odoo_url = f'https://{odoo_url}'

        # Try with and without trailing slash
        base_url = odoo_url.rstrip('/')
        urls_to_try = [base_url, f'{base_url}/']

        last_error = None
        self._uid = None

        for attempt_url in urls_to_try:
            try:
                logger.debug(f"Attempting Odoo connection", extra={"url": attempt_url})
                common = xmlrpc.client.ServerProxy(f"{attempt_url}/xmlrpc/2/common")
                uid = common.authenticate(settings.ODOO_DB, settings.ODOO_USERNAME, password, {})

                if uid:
                    logger.info("Odoo authentication successful", extra={"uid": uid})
                    self._uid = uid
                    odoo_url = base_url  # Use URL without trailing slash for consistency
                    break
                else:
                    last_error = "Authentication returned no UID (check username/password)"
            except xmlrpc.client.ProtocolError as e:
                last_error = f"ProtocolError {e.errcode}: {e.errmsg}"
                logger.debug(f"ProtocolError", extra={"url": attempt_url, "code": e.errcode, "msg": e.errmsg})
            except Exception as e:
                last_error = str(e)
                logger.debug(f"Connection error", extra={"url": attempt_url, "error": str(e)})

        if not self._uid:
            raise ConnectionError(
                f"Odoo authentication failed. Tried: {', '.join(urls_to_try)}. "
                f"Last error: {last_error}. "
                f"Verify: ODOO_URL, ODOO_DB={settings.ODOO_DB}, ODOO_USERNAME={settings.ODOO_USERNAME}"
            )

        self._models = xmlrpc.client.ServerProxy(f"{odoo_url}/xmlrpc/2/object")
        self._db = settings.ODOO_DB
        self._password = password

    def _execute(self, model: str, method: str, args: List[Any], kwargs: Dict[str, Any] | None = None) -> Any:
        return self._models.execute_kw(
            self._db, self._uid, self._password, model, method, args, kwargs or {}
        )

    def fetch_partners(self) -> List[Dict[str, Any]]:
        return self._execute(
            OdooModels.RES_PARTNER,
            OdooActions.SEARCH_READ,
            [[["phone", "!=", False]]],
            {
                "fields": [
                    OdooFieldsPartner.ID,
                    OdooFieldsPartner.NAME,
                    OdooFieldsPartner.PHONE,
                    OdooFieldsPartner.EMAIL
                ]
            },
        )

    def create_partner(self, name: str, phone: str, email: str | None = None) -> int:
        """
        Create a new contact in Odoo. Returns the Odoo partner ID.
        """
        phone = _normalize_phone(phone)
        if not phone:
            raise ValueError("Phone number must contain at least one digit")

        partner_id = self._execute(
            OdooModels.RES_PARTNER,
            OdooActions.CREATE,
            [{
                OdooFieldsPartner.NAME: name,
                OdooFieldsPartner.PHONE: phone,
                OdooFieldsPartner.EMAIL: email or False,
            }],
        )
        logger.info(LogMessages.ODOO_CONTACT_CREATED, extra={"partner_id": partner_id, "name": name})
        return partner_id

    def update_partner(self, partner_id: int, name: str | None = None, phone: str | None = None, email: str | None = None) -> bool:
        """
        Update an existing contact in Odoo. Returns True if successful.
        """
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if phone is not None:
            phone = _normalize_phone(phone)
            if not phone:
                raise ValueError("Phone number must contain at least one digit")
            update_data["phone"] = phone
        if email is not None:
            update_data["email"] = email or False

        if not update_data:
            return True  # Nothing to update

        self._execute("res.partner", "write", [[partner_id], update_data])
        logger.info("Contact updated in Odoo", extra={"partner_id": partner_id, "fields": list(update_data.keys())})
        return True

    def sync_contacts(self, db: Session) -> Dict[str, Any]:
        partners = self.fetch_partners()
        created = updated = skipped = 0

        for p in partners:
            raw_phone = p.get("phone") or ""
            phone = _normalize_phone(raw_phone)
            if not phone:
                skipped += 1
                continue

            email = p.get("email") or None
            if email is False:
                email = None

            # Prefer matching by Odoo partner ID (authoritative)
            contact = db.query(Contact).filter(Contact.odoo_partner_id == p["id"]).first()

            if contact:
                contact.name = p["name"]
                contact.phone = phone
                contact.email = email
                contact.last_synced_at = datetime.utcnow()
                updated += 1
            else:
                # Fall back to phone match to avoid duplicates
                contact = db.query(Contact).filter(Contact.phone == phone).first()
                if contact:
                    contact.odoo_partner_id = p["id"]
                    contact.name = p["name"]
                    contact.email = email
                    contact.last_synced_at = datetime.utcnow()
                    updated += 1
                else:
                    db.add(Contact(
                        name=p["name"],
                        phone=phone,
                        email=email,
                        odoo_partner_id=p["id"],
                        last_synced_at=datetime.utcnow(),
                    ))
                    created += 1

        db.commit()
        logger.info(
            "Odoo contact sync complete",
            extra={"contacts_created": created, "contacts_updated": updated, "contacts_skipped": skipped},
        )
        return {"created": created, "updated": updated, "skipped": skipped, "total": len(partners)}

    def fetch_customer_invoices(self, partner_id: int, limit: int = ApiDefaults.INVOICE_LIMIT) -> List[Dict[str, Any]]:
        """Fetch unpaid/open invoices for a customer. Returns empty list if model unavailable."""
        # Odoo 19+ uses account.move without due_date field, older versions may have it
        # Try multiple field combinations for compatibility across versions
        models_to_try = [
            (OdooModels.ACCOUNT_MOVE, [
                [OdooFieldsInvoice.PARTNER_ID, "=", partner_id],
                [OdooFieldsInvoice.MOVE_TYPE, "in", [OdooMoveTypes.OUT_INVOICE, OdooMoveTypes.OUT_REFUND]],
                [OdooFieldsInvoice.PAYMENT_STATE, "!=", OdooPaymentStates.PAID]
            ], [
                # Odoo 19+ compatible: no due_date
                [OdooFieldsInvoice.ID, OdooFieldsInvoice.NAME, OdooFieldsInvoice.INVOICE_DATE, OdooFieldsInvoice.AMOUNT_TOTAL, OdooFieldsInvoice.PAYMENT_STATE],
                # Fallback for older versions that have due_date
                [OdooFieldsInvoice.ID, OdooFieldsInvoice.NAME, OdooFieldsInvoice.INVOICE_DATE, OdooFieldsInvoice.DUE_DATE, OdooFieldsInvoice.AMOUNT_TOTAL, OdooFieldsInvoice.PAYMENT_STATE],
            ]),
            (OdooModels.ACCOUNT_INVOICE, [
                [OdooFieldsInvoice.PARTNER_ID, "=", partner_id],
                [OdooFieldsInvoice.PAYMENT_STATE, "!=", OdooPaymentStates.PAID]
            ], [
                [OdooFieldsInvoice.ID, OdooFieldsInvoice.NAME, OdooFieldsInvoice.INVOICE_DATE, OdooFieldsInvoice.DUE_DATE, OdooFieldsInvoice.AMOUNT_TOTAL, OdooFieldsInvoice.PAYMENT_STATE],
            ]),
        ]

        errors_encountered = []
        for model, domain, field_lists in models_to_try:
            # Try each field list for the model (in case some fields don't exist)
            field_lists = field_lists if isinstance(field_lists[0], list) else [field_lists]

            for fields in field_lists:
                try:
                    invoices = self._execute(
                        model,
                        "search_read",
                        [domain],
                        {
                            "fields": fields,
                            "order": "invoice_date DESC",
                            "limit": limit
                        }
                    )
                    logger.info(
                        "Customer invoices fetched",
                        extra={"partner_id": partner_id, "count": len(invoices), "model": model, "fields": fields}
                    )
                    return invoices
                except Exception as e:
                    error_msg = str(e)
                    logger.debug(
                        f"Model {model} with fields {fields} not available",
                        extra={"partner_id": partner_id, "error": error_msg}
                    )
                    continue

            errors_encountered.append(f"{model}: failed all field combinations")

        logger.warning(
            "Could not fetch invoices — no accounting model accessible. Check if accounting module is installed and enabled.",
            extra={"partner_id": partner_id, "models_tried": errors_encountered}
        )
        return []

    def fetch_customer_orders(self, partner_id: int, limit: int = ApiDefaults.ORDER_LIMIT) -> List[Dict[str, Any]]:
        """Fetch recent sales orders for a customer. Returns empty list if model unavailable."""
        try:
            orders = self._execute(
                "sale.order",
                "search_read",
                [[
                    ["partner_id", "=", partner_id],
                    ["state", "not in", ["draft", "cancel"]]
                ]],
                {
                    "fields": ["id", "name", "date_order", "state", "amount_total"],
                    "order": "date_order DESC",
                    "limit": limit
                }
            )
            logger.info(
                "Customer orders fetched",
                extra={"partner_id": partner_id, "count": len(orders)}
            )
            return orders
        except Exception as e:
            logger.warning(
                "Could not fetch orders — model may not exist or not accessible",
                extra={"partner_id": partner_id, "error": str(e)}
            )
            return []

    def fetch_customer_payments(self, partner_id: int, limit: int = ApiDefaults.PAYMENT_LIMIT) -> List[Dict[str, Any]]:
        """Fetch recent payments from a customer. Returns empty list if model unavailable."""
        try:
            payments = self._execute(
                OdooModels.ACCOUNT_PAYMENT,
                OdooActions.SEARCH_READ,
                [[
                    [OdooFieldsPayment.PARTNER_ID, "=", partner_id],
                    [OdooFieldsPayment.STATE, "=", OdooInvoiceStates.POSTED]
                ]],
                {
                    "fields": [
                        OdooFieldsPayment.ID,
                        OdooFieldsPayment.NAME,
                        OdooFieldsPayment.DATE,
                        OdooFieldsPayment.AMOUNT
                    ],
                    "order": OrderByField.DATE,
                    "limit": limit
                }
            )
            logger.info(
                "Customer payments fetched",
                extra={"partner_id": partner_id, "count": len(payments)}
            )
            return payments
        except Exception as e:
            logger.warning(
                "Could not fetch payments — model may not exist or not accessible",
                extra={"partner_id": partner_id, "error": str(e)}
            )
            return []

    def fetch_customer_context(self, partner_id: int) -> Dict[str, Any]:
        """Fetch complete customer business context for AI replies. Gracefully handles missing models."""
        try:
            partners = self._execute(
                "res.partner",
                "search_read",
                [[["id", "=", partner_id]]],
                {"fields": ["id", "name", "company_id"]}
            )
            partner = partners[0] if partners else {}

            # Fetch each data type independently - if one fails, continue with others
            invoices = self.fetch_customer_invoices(partner_id)
            orders = self.fetch_customer_orders(partner_id)
            payments = self.fetch_customer_payments(partner_id)

            has_data = bool(invoices or orders or payments)
            context = {
                "partner": partner,
                "invoices": invoices,
                "orders": orders,
                "payments": payments,
                "company_name": partner.get("name", ""),
                "access_success": True  # Odoo fetch succeeded
            }

            logger.info(
                "Customer context fetched successfully",
                extra={"partner_id": partner_id, "has_business_data": has_data}
            )
            return context
        except Exception as e:
            logger.error(
                "Error fetching customer context — Odoo access failed",
                extra={"partner_id": partner_id, "error": str(e)}
            )
            # Return empty context with failure flag
            return {
                "partner": {},
                "invoices": [],
                "orders": [],
                "payments": [],
                "company_name": "",
                "access_success": False  # Odoo fetch failed
            }

    def get_invoice_pdf(self, invoice_id: int) -> bytes:
        """
        Fetch invoice PDF from Odoo via custom API endpoint with token authentication.

        This uses the custom 'whatsapp_invoice_api' module installed in Odoo,
        which provides secure token-based PDF retrieval.

        Args:
            invoice_id: The Odoo invoice ID

        Returns:
            PDF bytes that can be uploaded to WhatsApp
        """
        try:
            # Use custom API endpoint with token authentication
            api_token = settings.ODOO_API_KEY
            api_url = f"{settings.ODOO_URL}/api/invoice/pdf/{invoice_id}"

            logger.info(
                "Fetching invoice PDF via custom Odoo API endpoint",
                extra={"invoice_id": invoice_id, "endpoint": "/api/invoice/pdf/"}
            )

            response = requests.get(
                api_url,
                params={"token": api_token},
                timeout=ApiTimeouts.ODOO_PDF_FETCH,
                verify=True,
                headers={"Accept": "application/pdf"}
            )

            # Handle different error cases
            if response.status_code == 401:
                logger.error(
                    "API authentication failed - token is invalid or expired",
                    extra={"invoice_id": invoice_id}
                )
                raise ValueError(
                    "Odoo API token invalid. Ensure the custom module is installed "
                    "and the API token is correct."
                )

            if response.status_code == 404:
                logger.warning(
                    "Invoice not found in Odoo",
                    extra={"invoice_id": invoice_id}
                )
                raise ValueError(f"Invoice {invoice_id} not found in Odoo")

            if response.status_code == 400:
                logger.warning(
                    "Bad request to API",
                    extra={"invoice_id": invoice_id, "response": response.text}
                )
                raise ValueError(f"Invalid invoice request: {response.text}")

            if response.status_code != 200:
                logger.error(
                    "Unexpected API response",
                    extra={
                        "invoice_id": invoice_id,
                        "status": response.status_code,
                        "response": response.text[:200]
                    }
                )
                raise ValueError(
                    f"Failed to fetch PDF from Odoo API (status {response.status_code})"
                )

            # Verify it's a valid PDF
            if not response.content.startswith(b"%PDF"):
                logger.error(
                    "Response is not a valid PDF",
                    extra={"invoice_id": invoice_id, "first_bytes": response.content[:20]}
                )
                raise ValueError("Odoo returned invalid PDF content")

            logger.info(
                "Invoice PDF fetched successfully from Odoo API",
                extra={
                    "invoice_id": invoice_id,
                    "size": len(response.content),
                    "source": "odoo_api"
                }
            )

            return response.content

        except requests.exceptions.ConnectionError as e:
            logger.error(
                "Failed to connect to Odoo API",
                extra={"invoice_id": invoice_id, "error": str(e)}
            )
            raise ValueError(f"Cannot reach Odoo instance: {str(e)}")

        except requests.exceptions.Timeout:
            logger.error(
                "Odoo API request timed out",
                extra={"invoice_id": invoice_id}
            )
            raise ValueError("Odoo API request timed out")

        except Exception as e:
            logger.error(
                "Failed to fetch invoice PDF from Odoo API",
                extra={"invoice_id": invoice_id, "error": str(e)}
            )

            # Fallback to local PDF generation if API fails
            logger.info(
                "Falling back to local PDF generation",
                extra={"invoice_id": invoice_id}
            )
            raise

    @staticmethod
    def _register_unicode_font() -> tuple[str, str]:
        """
        Register a TrueType font that supports the ₹ symbol.
        Returns (regular_font_name, bold_font_name).
        Falls back to Helvetica if no Unicode font is found.
        """
        import os
        try:
            from reportlab.pdfbase import pdfmetrics  # type: ignore
            from reportlab.pdfbase.ttfonts import TTFont  # type: ignore

            candidates = [
                # Linux / Render (Ubuntu/Debian)
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
                # Windows
                ("C:\\Windows\\Fonts\\arial.ttf",
                 "C:\\Windows\\Fonts\\arialbd.ttf"),
                ("C:\\Windows\\Fonts\\calibri.ttf",
                 "C:\\Windows\\Fonts\\calibrib.ttf"),
            ]
            for reg_path, bold_path in candidates:
                if os.path.exists(reg_path):
                    pdfmetrics.registerFont(TTFont("InvFont", reg_path))
                    if os.path.exists(bold_path):
                        pdfmetrics.registerFont(TTFont("InvFont-Bold", bold_path))
                        return "InvFont", "InvFont-Bold"
                    return "InvFont", "InvFont"
        except Exception:
            pass
        return "Helvetica", "Helvetica-Bold"

    def generate_invoice_pdf(self, invoice_data: Dict[str, Any]) -> bytes:
        """
        Generate a proper invoice PDF with header, Bill To, line items table, and totals.
        Line items are rendered when invoice_line_ids is present (from get_invoice);
        otherwise only the totals block is shown (context from fetch_customer_invoices).
        """
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab is not installed - PDF generation not available")

        try:
            from reportlab.lib.pagesizes import A4  # type: ignore
            from reportlab.lib import colors  # type: ignore
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable  # type: ignore
            from reportlab.lib.styles import ParagraphStyle  # type: ignore
            from reportlab.lib.units import mm  # type: ignore
            from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT  # type: ignore

            logger.info("Generating invoice PDF", extra={"invoice_name": invoice_data.get("name")})

            font_reg, font_bold = self._register_unicode_font()
            rupee = InvoiceDefaults.RUPEE_SYMBOL

            # ── Colours ──────────────────────────────────────────────────────
            BRAND_BLUE  = colors.HexColor("#1A3C6E")
            ACCENT_BLUE = colors.HexColor("#2563EB")
            LIGHT_BLUE  = colors.HexColor("#EBF2FF")
            ROW_ALT     = colors.HexColor("#F7F9FC")
            BORDER_GREY = colors.HexColor("#CBD5E1")
            TEXT_DARK   = colors.HexColor("#1E293B")
            TEXT_MUTED  = colors.HexColor("#64748B")
            GREEN       = colors.HexColor("#16A34A")
            ORANGE      = colors.HexColor("#D97706")
            RED         = colors.HexColor("#DC2626")

            # ── Page setup ───────────────────────────────────────────────────
            pdf_buffer = BytesIO()
            doc = SimpleDocTemplate(
                pdf_buffer,
                pagesize=A4,
                leftMargin=15 * mm,
                rightMargin=15 * mm,
                topMargin=12 * mm,
                bottomMargin=15 * mm,
            )
            page_w = A4[0] - 30 * mm

            # ── Styles ───────────────────────────────────────────────────────
            def sty(name, **kw):
                kw.setdefault("fontName", font_reg)
                return ParagraphStyle(name, **kw)

            s_company = sty("Co",   fontSize=20, textColor=colors.white, fontName=font_bold, leading=24)
            s_inv_lbl = sty("ILbl", fontSize=9,  textColor=colors.HexColor("#93C5FD"), alignment=TA_RIGHT)
            s_inv_num = sty("INum", fontSize=16, textColor=colors.white, fontName=font_bold, alignment=TA_RIGHT, leading=20)
            s_section = sty("Sec",  fontSize=8,  textColor=TEXT_MUTED, leading=11)
            s_label   = sty("Lbl",  fontSize=9,  textColor=TEXT_MUTED, leading=13)
            s_value   = sty("Val",  fontSize=10, textColor=TEXT_DARK,  fontName=font_bold, leading=14)
            s_body    = sty("Bod",  fontSize=10, textColor=TEXT_DARK,  leading=14)
            s_th      = sty("TH",   fontSize=10, textColor=colors.white, fontName=font_bold, leading=13)
            s_td      = sty("TD",   fontSize=9,  textColor=TEXT_DARK, leading=13)
            s_td_r    = sty("TDR",  fontSize=9,  textColor=TEXT_DARK, alignment=TA_RIGHT, leading=13)
            s_td_c    = sty("TDC",  fontSize=9,  textColor=TEXT_DARK, alignment=TA_CENTER, leading=13)
            s_tot_l   = sty("TotL", fontSize=10, textColor=TEXT_DARK, fontName=font_bold, leading=14)
            s_tot_r   = sty("TotR", fontSize=10, textColor=TEXT_DARK, fontName=font_bold, alignment=TA_RIGHT, leading=14)
            s_bal_l   = sty("BalL", fontSize=12, textColor=colors.white, fontName=font_bold, leading=16)
            s_bal_r   = sty("BalR", fontSize=12, textColor=colors.white, fontName=font_bold, alignment=TA_RIGHT, leading=16)
            s_footer  = sty("Ftr",  fontSize=8,  textColor=TEXT_MUTED, alignment=TA_CENTER, leading=12)

            # ── Extract data ─────────────────────────────────────────────────
            invoice_number = invoice_data.get("name", "N/A")
            invoice_date   = str(invoice_data.get("invoice_date") or "N/A")
            due_date       = str(invoice_data.get("due_date") or invoice_data.get("invoice_date") or "N/A")
            payment_state  = invoice_data.get("payment_state", "not_paid")
            payment_label  = payment_state.replace("_", " ").title()
            amount_total   = float(invoice_data.get("amount_total", 0) or 0)
            status_color   = GREEN if payment_state == "paid" else (ORANGE if payment_state == "partial" else RED)
            company_name   = getattr(settings, "COMPANY_NAME", "Flexmind Innovations")

            # partner_id is [id, "Name"] from XML-RPC or absent in context invoices
            raw_partner = invoice_data.get("partner_id", "")
            if isinstance(raw_partner, (list, tuple)) and len(raw_partner) >= 2:
                partner_name = str(raw_partner[1])
            elif isinstance(raw_partner, str) and raw_partner:
                partner_name = raw_partner
            else:
                partner_name = "Customer"

            # Line items — only present when invoice_data comes from get_invoice()
            raw_lines = invoice_data.get("invoice_line_ids") or []
            line_items = [l for l in raw_lines if isinstance(l, dict) and float(l.get("quantity", 0) or 0) != 0]

            elements = []

            # ── 1. HEADER BAND ───────────────────────────────────────────────
            # Inner table for INVOICE label + number — needs its own right padding
            # because the outer cell's RIGHTPADDING does not clip a nested Table.
            header_right_inner = Table(
                [[Paragraph("INVOICE", s_inv_lbl)],
                 [Paragraph(invoice_number, s_inv_num)]],
                colWidths=[page_w * 0.45],
            )
            header_right_inner.setStyle(TableStyle([
                ("RIGHTPADDING",  (0, 0), (-1, -1), 28),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ]))

            header_table = Table(
                [[Paragraph(company_name, s_company), header_right_inner]],
                colWidths=[page_w * 0.55, page_w * 0.45],
            )
            header_table.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), BRAND_BLUE),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING",   (0, 0), (0, -1),  28),
                ("RIGHTPADDING",  (1, 0), (1, -1),  0),
                ("TOPPADDING",    (0, 0), (-1, -1), 26),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 26),
            ]))
            elements.append(header_table)
            elements.append(HRFlowable(width="100%", thickness=3, color=ACCENT_BLUE, spaceAfter=12))

            # ── 2. BILL TO  |  INVOICE DETAILS ──────────────────────────────
            bill_to_inner = Table(
                [[Paragraph("BILL TO", s_section)],
                 [Paragraph(partner_name, s_value)]],
                colWidths=[page_w * 0.48],
            )
            inv_detail_rows = [
                [Paragraph("Invoice No",   s_label), Paragraph(invoice_number, s_body)],
                [Paragraph("Invoice Date", s_label), Paragraph(invoice_date,   s_body)],
                [Paragraph("Due Date",     s_label), Paragraph(due_date,       s_body)],
                [Paragraph("Status",       s_label),
                 Paragraph(payment_label, ParagraphStyle("St", parent=s_body, textColor=status_color, fontName=font_bold))],
            ]
            inv_detail_inner = Table(inv_detail_rows, colWidths=[page_w * 0.22, page_w * 0.26])
            inv_detail_inner.setStyle(TableStyle([
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ]))
            info_row = Table([[bill_to_inner, inv_detail_inner]], colWidths=[page_w * 0.52, page_w * 0.48])
            info_row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING",   (0, 0), (0, -1),  12),
                ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BLUE),
                ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_GREY),
                ("LINEAFTER",     (0, 0), (0, -1),  0.5, BORDER_GREY),
            ]))
            elements.append(info_row)
            elements.append(Spacer(1, 6 * mm))

            # ── 3. LINE ITEMS TABLE (when available) ─────────────────────────
            subtotal = 0.0
            if line_items:
                col_w = [page_w * 0.50, page_w * 0.12, page_w * 0.19, page_w * 0.19]
                rows = [[
                    Paragraph("Description", s_th),
                    Paragraph("Qty",    ParagraphStyle("ThC", parent=s_th, alignment=TA_CENTER)),
                    Paragraph("Rate",   ParagraphStyle("ThR", parent=s_th, alignment=TA_RIGHT)),
                    Paragraph("Amount", ParagraphStyle("ThA", parent=s_th, alignment=TA_RIGHT)),
                ]]
                for line in line_items:
                    # name can be a description string; product_id is [id, name] if present
                    desc  = line.get("name") or (
                        line["product_id"][1] if isinstance(line.get("product_id"), (list, tuple)) and len(line["product_id"]) >= 2
                        else "—"
                    )
                    qty   = float(line.get("quantity", 1) or 1)
                    rate  = float(line.get("price_unit", 0) or 0)
                    total = float(line.get("price_subtotal", qty * rate) or 0)
                    subtotal += total
                    rows.append([
                        Paragraph(str(desc), s_td),
                        Paragraph(f"{qty:g}",              s_td_c),
                        Paragraph(f"{rupee} {rate:,.2f}",  s_td_r),
                        Paragraph(f"{rupee} {total:,.2f}", s_td_r),
                    ])

                items_table = Table(rows, colWidths=col_w, repeatRows=1)
                ts = TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_BLUE),
                    ("TOPPADDING",    (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                    ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_GREY),
                    ("LINEBELOW",     (0, 0), (-1, -1), 0.3, BORDER_GREY),
                    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ])
                for i in range(1, len(rows)):
                    ts.add("BACKGROUND", (0, i), (-1, i), colors.white if i % 2 == 1 else ROW_ALT)
                items_table.setStyle(ts)
                elements.append(items_table)
            else:
                subtotal = amount_total

            elements.append(Spacer(1, 4 * mm))

            # ── 4. TOTALS BLOCK (right-aligned) ──────────────────────────────
            if payment_state == "paid":
                amount_paid = amount_total
                balance_due = 0.0
            else:
                amount_paid = 0.0
                balance_due = amount_total

            totals_rows: list = []
            if line_items:
                totals_rows.append([Paragraph("Subtotal", s_tot_l), Paragraph(f"{rupee} {subtotal:,.2f}", s_tot_r)])
            totals_rows.append([Paragraph("Total", s_tot_l), Paragraph(f"{rupee} {amount_total:,.2f}", s_tot_r)])
            if amount_paid > 0:
                totals_rows.append([
                    Paragraph(f"Paid ({payment_label})", s_tot_l),
                    Paragraph(f"- {rupee} {amount_paid:,.2f}", s_tot_r),
                ])
            # Balance due — dark highlight row
            totals_rows.append([Paragraph("Balance Due", s_bal_l), Paragraph(f"{rupee} {balance_due:,.2f}", s_bal_r)])

            n = len(totals_rows)
            totals_table = Table(totals_rows, colWidths=[page_w * 0.42, page_w * 0.18])
            ts2 = TableStyle([
                ("TOPPADDING",    (0, 0),    (-1, -1),   6),
                ("BOTTOMPADDING", (0, 0),    (-1, -1),   6),
                ("LEFTPADDING",   (0, 0),    (-1, -1),   12),
                ("RIGHTPADDING",  (0, 0),    (-1, -1),   12),
                ("LINEBELOW",     (0, 0),    (-1, n - 2), 0.3, BORDER_GREY),
                ("BOX",           (0, 0),    (-1, n - 2), 0.5, BORDER_GREY),
                ("BACKGROUND",    (0, 0),    (-1, n - 2), colors.white),
                ("BACKGROUND",    (0, n - 1), (-1, n - 1), BRAND_BLUE),
                ("TOPPADDING",    (0, n - 1), (-1, n - 1), 10),
                ("BOTTOMPADDING", (0, n - 1), (-1, n - 1), 10),
            ])
            totals_table.setStyle(ts2)

            # Spacer on the left pushes totals to the right
            wrapper = Table(
                [[Paragraph("", s_label), totals_table]],
                colWidths=[page_w * 0.4, page_w * 0.6],
            )
            wrapper.setStyle(TableStyle([
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))
            elements.append(wrapper)
            elements.append(Spacer(1, 10 * mm))

            # ── 5. FOOTER ────────────────────────────────────────────────────
            elements.append(HRFlowable(width="100%", thickness=1, color=BORDER_GREY, spaceAfter=6))
            support_email = getattr(settings, "COMPANY_EMAIL", "support@flexmindinnovations.com")
            elements.append(Paragraph(
                f"Thank you for your business. For queries regarding this invoice, "
                f"please contact us at {support_email}.",
                s_footer,
            ))

            doc.build(elements)
            pdf_bytes = pdf_buffer.getvalue()
            logger.info("Invoice PDF generated", extra={"invoice_name": invoice_number, "size": len(pdf_bytes)})
            return pdf_bytes

        except Exception as e:
            logger.error("Failed to generate invoice PDF",
                         extra={"invoice_name": invoice_data.get("name"), "error": str(e)})
            raise

    def list_all_invoices(self, limit: int = Pagination.DEFAULT_LIMIT, offset: int = ApiDefaults.DEFAULT_OFFSET) -> List[Dict[str, Any]]:
        """Fetch all customer invoices."""
        try:
            invoices = self._execute(
                OdooModels.ACCOUNT_MOVE,
                OdooActions.SEARCH_READ,
                [[[OdooFieldsInvoice.MOVE_TYPE, "=", OdooMoveTypes.OUT_INVOICE]]],
                {
                    "fields": [
                        OdooFieldsInvoice.ID,
                        OdooFieldsInvoice.NAME,
                        OdooFieldsInvoice.PARTNER_ID,
                        OdooFieldsInvoice.INVOICE_DATE,
                        OdooFieldsInvoice.AMOUNT_TOTAL,
                        OdooFieldsInvoice.STATE,
                        OdooFieldsInvoice.PAYMENT_STATE
                    ],
                    "order": OrderByField.INVOICE_DATE,
                    "limit": limit,
                    "offset": offset
                }
            )
            return invoices
        except Exception as e:
            logger.error("Failed to list all invoices from Odoo", extra={"error": str(e)})
            raise ValueError(f"Odoo error listing invoices: {str(e)}")

    def get_invoice(self, invoice_id: int) -> Dict[str, Any]:
        """Fetch invoice details including its lines."""
        try:
            invoices = self._execute(
                "account.move",
                "read",
                [[invoice_id]],
                {"fields": ["id", "name", "partner_id", "invoice_date", "amount_total", "state", "payment_state", "invoice_line_ids"]}
            )
            if not invoices:
                raise ValueError(f"Invoice {invoice_id} not found in Odoo")
            invoice = invoices[0]
            
            # Fetch invoice lines details
            if invoice.get("invoice_line_ids"):
                lines = self._execute(
                    "account.move.line",
                    "read",
                    [invoice["invoice_line_ids"]],
                    {"fields": ["id", "name", "quantity", "price_unit", "price_subtotal"]}
                )
                invoice["invoice_line_ids"] = lines
            else:
                invoice["invoice_line_ids"] = []
                
            return invoice
        except Exception as e:
            logger.error(f"Failed to fetch invoice {invoice_id} from Odoo", extra={"error": str(e)})
            raise ValueError(f"Odoo error fetching invoice: {str(e)}")

    def create_invoice(self, partner_id: int, invoice_date: str | None = None, lines: List[Dict[str, Any]] | None = None) -> int:
        """
        Create a new draft invoice in Odoo. Returns the created Odoo invoice ID.
        """
        if not invoice_date:
            invoice_date = datetime.now().strftime("%Y-%m-%d")
            
        line_commands = []
        if lines:
            for line in lines:
                line_commands.append((0, 0, {
                    "name": line.get("name", "Product/Service"),
                    "quantity": line.get("quantity", 1),
                    "price_unit": line.get("price_unit", 0.0),
                }))
                
        invoice_vals = {
            "move_type": "out_invoice",
            "partner_id": partner_id,
            "invoice_date": invoice_date,
            "invoice_line_ids": line_commands,
        }
        
        try:
            invoice_id = self._execute("account.move", "create", [invoice_vals])
            logger.info("Invoice created in Odoo", extra={"invoice_id": invoice_id})
            return invoice_id
        except Exception as e:
            logger.error("Failed to create invoice in Odoo", extra={"error": str(e)})
            raise ValueError(f"Odoo error creating invoice: {str(e)}")

    def post_invoice(self, invoice_id: int) -> bool:
        """
        Validate/confirm a draft invoice in Odoo.
        """
        try:
            self._execute("account.move", "action_post", [[invoice_id]])
            logger.info("Invoice posted in Odoo", extra={"invoice_id": invoice_id})
            return True
        except Exception as e:
            logger.error(f"Failed to post invoice {invoice_id} in Odoo", extra={"error": str(e)})
            raise ValueError(f"Odoo error posting invoice: {str(e)}")


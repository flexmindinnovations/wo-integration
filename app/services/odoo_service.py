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
        Fetch the official Odoo invoice PDF. Tries three strategies in order:
          1. Custom module API  (/api/invoice/pdf/{id}?token=...)
          2. HTTP session auth  (/web/session/authenticate → /report/pdf/...)
          3. XML-RPC            (ir.actions.report.render_qweb_pdf)

        Raises ValueError if all three fail.
        """
        errors: list[str] = []

        # ── Strategy 1: custom module API ────────────────────────────────────
        try:
            return self._fetch_pdf_custom_api(invoice_id)
        except Exception as e:
            errors.append(f"custom_api: {e}")
            logger.debug("Custom API PDF fetch failed", extra={"invoice_id": invoice_id, "error": str(e)})

        # ── Strategy 2: standard Odoo report via HTTP session ─────────────────
        try:
            return self._fetch_pdf_http_session(invoice_id)
        except Exception as e:
            errors.append(f"http_session: {e}")
            logger.debug("HTTP session PDF fetch failed", extra={"invoice_id": invoice_id, "error": str(e)})

        # ── Strategy 3: XML-RPC render_qweb_pdf (Odoo 14–17) ─────────────────
        try:
            return self._fetch_pdf_xmlrpc(invoice_id)
        except Exception as e:
            errors.append(f"xmlrpc: {e}")
            logger.debug("XML-RPC PDF fetch failed", extra={"invoice_id": invoice_id, "error": str(e)})

        raise ValueError(
            f"All Odoo PDF fetch strategies failed for invoice {invoice_id}: "
            + " | ".join(errors)
        )

    # ── PDF fetch helpers ─────────────────────────────────────────────────────

    def _fetch_pdf_custom_api(self, invoice_id: int) -> bytes:
        """Strategy 1: custom whatsapp_invoice_api module endpoint."""
        api_token = settings.ODOO_API_KEY
        if not api_token:
            raise ValueError("ODOO_API_KEY not set — custom API unavailable")
        url = f"{settings.ODOO_URL}/api/invoice/pdf/{invoice_id}"
        resp = requests.get(
            url,
            params={"token": api_token},
            headers={"Accept": "application/pdf"},
            timeout=ApiTimeouts.ODOO_PDF_FETCH,
        )
        if resp.status_code != 200:
            raise ValueError(f"Custom API returned HTTP {resp.status_code}: {resp.text[:200]}")
        if not resp.content.startswith(b"%PDF"):
            raise ValueError("Custom API response is not a valid PDF")
        logger.info("Invoice PDF fetched via custom API", extra={"invoice_id": invoice_id, "size": len(resp.content)})
        return resp.content

    def _fetch_pdf_http_session(self, invoice_id: int) -> bytes:
        """
        Strategy 2: standard Odoo report URL.
        POST /web/session/authenticate  →  GET /report/pdf/account.report_invoice/{id}
        Works with any Odoo version that has the accounting module.
        """
        password = settings.ODOO_PASSWORD or settings.ODOO_API_KEY
        session = requests.Session()

        auth_resp = session.post(
            f"{settings.ODOO_URL}/web/session/authenticate",
            json={
                "jsonrpc": "2.0", "method": "call", "id": 1,
                "params": {
                    "db": settings.ODOO_DB,
                    "login": settings.ODOO_USERNAME,
                    "password": password,
                },
            },
            timeout=ApiTimeouts.ODOO_PDF_FETCH,
        )
        auth_data = auth_resp.json()
        uid = (auth_data.get("result") or {}).get("uid")
        if not uid:
            msg = (auth_data.get("error") or {}).get("data", {}).get("message", "auth failed")
            raise ValueError(f"Session authenticate failed: {msg}")

        pdf_resp = session.get(
            f"{settings.ODOO_URL}/report/pdf/account.report_invoice/{invoice_id}",
            timeout=ApiTimeouts.ODOO_PDF_FETCH,
        )
        if pdf_resp.status_code != 200:
            raise ValueError(f"Report download returned HTTP {pdf_resp.status_code}")
        if not pdf_resp.content.startswith(b"%PDF"):
            raise ValueError("Report response is not a valid PDF")

        logger.info("Invoice PDF fetched via HTTP session", extra={"invoice_id": invoice_id, "size": len(pdf_resp.content)})
        return pdf_resp.content

    def _fetch_pdf_xmlrpc(self, invoice_id: int) -> bytes:
        """
        Strategy 3: XML-RPC ir.actions.report.render_qweb_pdf.
        Works on Odoo 14–17. May be restricted on Odoo 18+.
        """
        import base64

        reports = self._execute(
            "ir.actions.report",
            "search_read",
            [[["report_name", "=", "account.report_invoice"]]],
            {"fields": ["id"], "limit": 1},
        )
        if not reports:
            raise ValueError("account.report_invoice action not found in Odoo")

        report_id = reports[0]["id"]
        result = self._execute(
            "ir.actions.report",
            "render_qweb_pdf",
            [[report_id], [invoice_id]],
        )

        if not isinstance(result, (list, tuple)) or not result:
            raise ValueError(f"Unexpected render_qweb_pdf result type: {type(result)}")

        raw = result[0]
        if isinstance(raw, bytes):
            pdf_bytes = raw if raw.startswith(b"%PDF") else base64.b64decode(raw)
        else:
            pdf_bytes = base64.b64decode(raw.encode() if isinstance(raw, str) else raw)

        if not pdf_bytes.startswith(b"%PDF"):
            raise ValueError("XML-RPC render_qweb_pdf did not return a valid PDF")

        logger.info("Invoice PDF fetched via XML-RPC", extra={"invoice_id": invoice_id, "size": len(pdf_bytes)})
        return pdf_bytes

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

    @staticmethod
    def _amount_to_words(amount: float) -> str:
        """Convert a numeric amount to English words (Indian number system)."""
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
                "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
                "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens_w = ["", "", "Twenty", "Thirty", "Forty", "Fifty",
                  "Sixty", "Seventy", "Eighty", "Ninety"]

        def say(n: int) -> str:
            if n == 0:
                return ""
            if n < 20:
                return ones[n]
            if n < 100:
                return (tens_w[n // 10] + " " + ones[n % 10]).strip()
            if n < 1_000:
                return (ones[n // 100] + " Hundred " + say(n % 100)).strip()
            if n < 1_00_000:
                return (say(n // 1_000) + " Thousand " + say(n % 1_000)).strip()
            if n < 1_00_00_000:
                return (say(n // 1_00_000) + " Lakh " + say(n % 1_00_000)).strip()
            return (say(n // 1_00_00_000) + " Crore " + say(n % 1_00_00_000)).strip()

        int_part = int(amount)
        paise = round((amount - int_part) * 100)
        words = say(int_part) if int_part > 0 else "Zero"
        result = words + " Rupees"
        if paise:
            result += " and " + say(paise) + " Paise"
        return result

    def generate_invoice_pdf(self, invoice_data: Dict[str, Any]) -> bytes:
        """
        Generate a clean invoice PDF matching Odoo's default print layout:
        company / customer → large invoice heading → date fields →
        line items → totals + amount in words → footer.
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

            # ── Colours (Odoo-style palette) ──────────────────────────────────
            C_DARK   = colors.HexColor("#1A1A2E")   # near-black body text
            C_MUTED  = colors.HexColor("#64748B")   # grey labels
            C_ACCENT = colors.HexColor("#875A7B")   # Odoo purple – customer name
            C_TEAL   = colors.HexColor("#017E7C")   # Odoo teal – headings / rule
            C_ORANGE = colors.HexColor("#D97706")   # total amount highlight
            C_RULE   = colors.HexColor("#CBD5E1")   # light divider
            C_ALT    = colors.HexColor("#F8F9FA")   # alternate row tint

            # ── Page setup ───────────────────────────────────────────────────
            pdf_buffer = BytesIO()
            doc = SimpleDocTemplate(
                pdf_buffer,
                pagesize=A4,
                leftMargin=18 * mm, rightMargin=18 * mm,
                topMargin=14 * mm,  bottomMargin=14 * mm,
            )
            page_w = A4[0] - 36 * mm

            # ── Styles ───────────────────────────────────────────────────────
            def sty(name, **kw):
                kw.setdefault("fontName", font_reg)
                return ParagraphStyle(name, **kw)

            s_company   = sty("Co",   fontSize=16, fontName=font_bold, textColor=C_DARK,   leading=20)
            s_cust_lbl  = sty("CL",   fontSize=8,  textColor=C_MUTED,  leading=10,  alignment=TA_RIGHT)
            s_cust_name = sty("CN",   fontSize=12, fontName=font_bold, textColor=C_ACCENT, leading=15, alignment=TA_RIGHT)
            s_inv_head  = sty("IH",   fontSize=22, fontName=font_bold, textColor=C_DARK,   leading=28)
            s_date_lbl  = sty("DL",   fontSize=9,  fontName=font_bold, textColor=C_DARK,   leading=12)
            s_date_val  = sty("DV",   fontSize=10, textColor=C_DARK,   leading=14)
            s_col_hdr   = sty("CH",   fontSize=9,  fontName=font_bold, textColor=C_TEAL,   leading=12)
            s_col_hdr_r = sty("CHR",  fontSize=9,  fontName=font_bold, textColor=C_TEAL,   leading=12, alignment=TA_RIGHT)
            s_col_hdr_c = sty("CHC",  fontSize=9,  fontName=font_bold, textColor=C_TEAL,   leading=12, alignment=TA_CENTER)
            s_td        = sty("TD",   fontSize=9,  textColor=C_DARK,   leading=13)
            s_td_r      = sty("TDR",  fontSize=9,  textColor=C_DARK,   leading=13, alignment=TA_RIGHT)
            s_td_c      = sty("TDC",  fontSize=9,  textColor=C_DARK,   leading=13, alignment=TA_CENTER)
            s_note      = sty("NT",   fontSize=9,  textColor=C_TEAL,   leading=13)
            s_note_val  = sty("NV",   fontSize=9,  textColor=C_DARK,   leading=13)
            s_tot_lbl   = sty("TL",   fontSize=10, fontName=font_bold, textColor=C_DARK,   leading=14, alignment=TA_RIGHT)
            s_tot_val   = sty("TV",   fontSize=10, fontName=font_bold, textColor=C_ORANGE, leading=14, alignment=TA_RIGHT)
            s_words_lbl = sty("WL",   fontSize=9,  fontName=font_bold, textColor=C_DARK,   leading=12, alignment=TA_RIGHT)
            s_words_val = sty("WV",   fontSize=9,  textColor=C_MUTED,  leading=12, alignment=TA_RIGHT)
            s_footer    = sty("Ftr",  fontSize=8,  textColor=C_MUTED,  leading=11, alignment=TA_CENTER)

            # ── Extract data ─────────────────────────────────────────────────
            invoice_number = invoice_data.get("name", "N/A")
            invoice_date   = str(invoice_data.get("invoice_date") or "N/A")
            due_date       = str(
                invoice_data.get("invoice_date_due") or
                invoice_data.get("due_date") or
                invoice_data.get("invoice_date") or "N/A"
            )
            payment_state  = invoice_data.get("payment_state", "not_paid")
            amount_total   = float(invoice_data.get("amount_total", 0) or 0)
            company_name   = getattr(settings, "COMPANY_NAME", "Flexmind Innovations")
            support_email  = getattr(settings, "COMPANY_EMAIL", "support@flexmindinnovations.com")

            raw_partner = invoice_data.get("partner_id", "")
            if isinstance(raw_partner, (list, tuple)) and len(raw_partner) >= 2:
                partner_name = str(raw_partner[1])
            elif isinstance(raw_partner, str) and raw_partner:
                partner_name = raw_partner
            else:
                partner_name = "Customer"

            # Payment term (optional — Many2one returns [id, name])
            raw_term = invoice_data.get("invoice_payment_term_id")
            payment_term = str(raw_term[1]) if isinstance(raw_term, (list, tuple)) and len(raw_term) >= 2 else ""
            payment_ref  = (
                invoice_data.get("payment_reference") or
                invoice_data.get("ref") or
                invoice_number
            )

            raw_lines = invoice_data.get("invoice_line_ids") or []
            line_items = [l for l in raw_lines if isinstance(l, dict) and float(l.get("quantity", 0) or 0) != 0]

            P = Paragraph  # shorthand
            elements = []

            # ── 1. TOP ROW: company (left) | customer (right) ────────────────
            top_row = Table(
                [[
                    P(company_name, s_company),
                    Table(
                        [[P("Bill To", s_cust_lbl)], [P(partner_name, s_cust_name)]],
                        colWidths=[page_w * 0.45],
                    ),
                ]],
                colWidths=[page_w * 0.55, page_w * 0.45],
            )
            top_row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(top_row)
            elements.append(Spacer(1, 8 * mm))

            # ── 2. INVOICE HEADING ───────────────────────────────────────────
            elements.append(P(f"Invoice {invoice_number}", s_inv_head))
            elements.append(Spacer(1, 4 * mm))

            # ── 3. DATE FIELDS ───────────────────────────────────────────────
            date_row = Table(
                [[
                    Table([[P("Invoice Date", s_date_lbl)], [P(invoice_date, s_date_val)]], colWidths=[page_w * 0.25]),
                    Table([[P("Due Date",      s_date_lbl)], [P(due_date,     s_date_val)]], colWidths=[page_w * 0.25]),
                    P("", s_date_lbl),
                ]],
                colWidths=[page_w * 0.25, page_w * 0.25, page_w * 0.5],
            )
            date_row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(date_row)
            elements.append(Spacer(1, 4 * mm))
            elements.append(HRFlowable(width="100%", thickness=1.5, color=C_TEAL, spaceAfter=8))

            # ── 4. LINE ITEMS TABLE ──────────────────────────────────────────
            subtotal = 0.0
            if line_items:
                col_w = [page_w * 0.50, page_w * 0.13, page_w * 0.18, page_w * 0.19]
                rows = [[
                    P("Description", s_col_hdr),
                    P("Quantity",    s_col_hdr_c),
                    P("Unit Price",  s_col_hdr_r),
                    P("Amount",      s_col_hdr_r),
                ]]
                for line in line_items:
                    desc  = line.get("name") or (
                        line["product_id"][1]
                        if isinstance(line.get("product_id"), (list, tuple)) and len(line["product_id"]) >= 2
                        else "—"
                    )
                    qty   = float(line.get("quantity",      1)   or 1)
                    rate  = float(line.get("price_unit",    0)   or 0)
                    total = float(line.get("price_subtotal", qty * rate) or 0)
                    subtotal += total
                    rows.append([
                        P(str(desc),              s_td),
                        P(f"{qty:g}",             s_td_c),
                        P(f"{rate:,.2f}",         s_td_r),
                        P(f"{rupee} {total:,.2f}", s_td_r),
                    ])

                items_table = Table(rows, colWidths=col_w, repeatRows=1)
                ts = TableStyle([
                    ("LINEBELOW",     (0, 0), (-1, 0),  0.8, C_TEAL),
                    ("TOPPADDING",    (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                    ("LINEBELOW",     (0, 1), (-1, -1), 0.3, C_RULE),
                    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ])
                for i in range(1, len(rows)):
                    if i % 2 == 0:
                        ts.add("BACKGROUND", (0, i), (-1, i), C_ALT)
                items_table.setStyle(ts)
                elements.append(items_table)
            else:
                subtotal = amount_total

            elements.append(Spacer(1, 6 * mm))

            # ── 5. BOTTOM SECTION: notes (left) | total (right) ─────────────
            note_rows = []
            if payment_term:
                note_rows.append([P("Payment terms:", s_note), P(payment_term, s_note_val)])
            note_rows.append([P("Payment Communication:", s_note), P(str(payment_ref), s_note_val)])

            left_inner = Table(note_rows, colWidths=[page_w * 0.30, page_w * 0.22])
            left_inner.setStyle(TableStyle([
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ]))

            right_inner = Table(
                [[P("Total", s_tot_lbl), P(f"{rupee} {amount_total:,.2f}", s_tot_val)]],
                colWidths=[page_w * 0.20, page_w * 0.28],
            )
            right_inner.setStyle(TableStyle([
                ("LINEABOVE",     (0, 0), (-1, 0),  1.0, C_TEAL),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))

            bottom_row = Table(
                [[left_inner, right_inner]],
                colWidths=[page_w * 0.52, page_w * 0.48],
            )
            bottom_row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(bottom_row)
            elements.append(Spacer(1, 5 * mm))

            # ── 6. TOTAL AMOUNT IN WORDS ─────────────────────────────────────
            amount_words = self._amount_to_words(amount_total)
            words_row = Table(
                [[
                    P("", s_words_lbl),
                    Table(
                        [[P("Total amount in words:", s_words_lbl)],
                         [P(amount_words, s_words_val)]],
                        colWidths=[page_w * 0.45],
                    ),
                ]],
                colWidths=[page_w * 0.55, page_w * 0.45],
            )
            words_row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(words_row)
            elements.append(Spacer(1, 14 * mm))

            # ── 7. FOOTER ────────────────────────────────────────────────────
            elements.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceAfter=4))
            elements.append(P(support_email, s_footer))

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
                {"fields": [
                    "id", "name", "partner_id",
                    "invoice_date", "invoice_date_due",
                    "amount_total", "amount_tax",
                    "state", "payment_state",
                    "invoice_line_ids",
                    "invoice_payment_term_id",
                    "payment_reference", "ref",
                ]}
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
                    {"fields": ["id", "name", "quantity", "price_unit", "price_subtotal", "tax_ids"]}
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


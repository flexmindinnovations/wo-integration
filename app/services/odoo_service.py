import logging
import xmlrpc.client
import requests
from datetime import datetime
from sqlalchemy.orm import Session

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

# Try to import reportlab for PDF generation fallback
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
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

    def _execute(self, model: str, method: str, args: list, kwargs: dict | None = None) -> list:
        return self._models.execute_kw(
            self._db, self._uid, self._password, model, method, args, kwargs or {}
        )

    def fetch_partners(self) -> list[dict]:
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

    def sync_contacts(self, db: Session) -> dict:
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

    def fetch_customer_invoices(self, partner_id: int, limit: int = ApiDefaults.INVOICE_LIMIT) -> list[dict]:
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

    def fetch_customer_orders(self, partner_id: int, limit: int = 5) -> list[dict]:
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

    def fetch_customer_payments(self, partner_id: int, limit: int = ApiDefaults.PAYMENT_LIMIT) -> list[dict]:
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

    def fetch_customer_context(self, partner_id: int) -> dict:
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

    def generate_invoice_pdf(self, invoice_data: dict) -> bytes:
        """
        Generate a PDF from invoice data as a fallback when Odoo PDF fetch fails.

        Args:
            invoice_data: Dictionary with keys: name, amount_total, invoice_date, payment_state, due_date (optional)

        Returns:
            PDF bytes that can be uploaded to WhatsApp
        """
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab is not installed - PDF generation not available")

        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib.enums import TA_CENTER

            logger.info(
                "Generating invoice PDF from data",
                extra={"invoice_name": invoice_data.get("name")}
            )

            # Create PDF in memory
            pdf_buffer = BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            elements = []

            # Title
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#1f4788'),
                spaceAfter=30,
                alignment=TA_CENTER
            )
            elements.append(Paragraph("INVOICE", title_style))
            elements.append(Spacer(1, 0.3 * inch))

            # Invoice details
            invoice_number = invoice_data.get("name", "N/A")
            invoice_date = invoice_data.get("invoice_date", "N/A")
            due_date = invoice_data.get("due_date", invoice_data.get("invoice_date", "N/A"))
            amount = invoice_data.get("amount_total", 0)
            payment_state = invoice_data.get("payment_state", "unknown").replace("_", " ").title()

            # Details table with proper rupee symbol
            details_data = [
                ["Invoice Number:", invoice_number],
                ["Invoice Date:", str(invoice_date)],
                ["Due Date:", str(due_date)],
                [f"Amount ({InvoiceDefaults.CURRENCY}):", f"{InvoiceDefaults.RUPEE_SYMBOL} {amount:,.2f}"],
                ["Status:", payment_state],
            ]

            details_table = Table(details_data, colWidths=[2 * inch, 4 * inch])
            details_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))

            elements.append(details_table)
            elements.append(Spacer(1, 0.5 * inch))

            # Footer
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.grey,
                alignment=TA_CENTER
            )
            elements.append(Paragraph(
                "This is a summary invoice generated from your account.<br/>For official invoices, please log into your Flexmind Innovations account portal.",
                footer_style
            ))

            # Build PDF
            doc.build(elements)
            pdf_bytes = pdf_buffer.getvalue()

            logger.info(
                "Invoice PDF generated successfully",
                extra={"invoice_name": invoice_number, "size": len(pdf_bytes)}
            )
            return pdf_bytes

        except Exception as e:
            logger.error(
                "Failed to generate invoice PDF",
                extra={"invoice_name": invoice_data.get("name"), "error": str(e)}
            )
            raise

    def list_all_invoices(self, limit: int = Pagination.DEFAULT_LIMIT, offset: int = ApiDefaults.DEFAULT_OFFSET) -> list[dict]:
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

    def get_invoice(self, invoice_id: int) -> dict:
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

    def create_invoice(self, partner_id: int, invoice_date: str | None = None, lines: list[dict] = None) -> int:
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


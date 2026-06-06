import logging
import xmlrpc.client
import requests
import base64
from datetime import datetime
from io import BytesIO
from sqlalchemy.orm import Session

from app.config import settings
from app.models.contact import Contact

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

        common = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/common")
        self._uid = common.authenticate(settings.ODOO_DB, settings.ODOO_USERNAME, password, {})
        if not self._uid:
            raise ConnectionError("Odoo authentication failed — check credentials")

        self._models = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/object")
        self._db = settings.ODOO_DB
        self._password = password

    def _execute(self, model: str, method: str, args: list, kwargs: dict | None = None) -> list:
        return self._models.execute_kw(
            self._db, self._uid, self._password, model, method, args, kwargs or {}
        )

    def fetch_partners(self) -> list[dict]:
        return self._execute(
            "res.partner",
            "search_read",
            [[["phone", "!=", False]]],
            {"fields": ["id", "name", "phone", "email"]},
        )

    def create_partner(self, name: str, phone: str, email: str | None = None) -> int:
        """
        Create a new contact in Odoo. Returns the Odoo partner ID.
        """
        phone = _normalize_phone(phone)
        if not phone:
            raise ValueError("Phone number must contain at least one digit")

        partner_id = self._execute(
            "res.partner",
            "create",
            [{
                "name": name,
                "phone": phone,
                "email": email or False,
            }],
        )
        logger.info("Contact created in Odoo", extra={"partner_id": partner_id, "name": name})
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

    def fetch_customer_invoices(self, partner_id: int, limit: int = 5) -> list[dict]:
        """Fetch unpaid/open invoices for a customer. Returns empty list if model unavailable."""
        # Odoo 19+ uses account.move without due_date field, older versions may have it
        # Try multiple field combinations for compatibility across versions
        models_to_try = [
            ("account.move", [
                ["partner_id", "=", partner_id],
                ["move_type", "in", ["out_invoice", "out_refund"]],
                ["payment_state", "!=", "paid"]
            ], [
                # Odoo 19+ compatible: no due_date
                ["id", "name", "invoice_date", "amount_total", "payment_state"],
                # Fallback for older versions that have due_date
                ["id", "name", "invoice_date", "due_date", "amount_total", "payment_state"],
            ]),
            ("account.invoice", [
                ["partner_id", "=", partner_id],
                ["payment_state", "!=", "paid"]
            ], [
                ["id", "name", "invoice_date", "due_date", "amount_total", "payment_state"],
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

    def fetch_customer_payments(self, partner_id: int, limit: int = 3) -> list[dict]:
        """Fetch recent payments from a customer. Returns empty list if model unavailable."""
        try:
            payments = self._execute(
                "account.payment",
                "search_read",
                [[
                    ["partner_id", "=", partner_id],
                    ["state", "=", "posted"]
                ]],
                {
                    "fields": ["id", "name", "date", "amount"],
                    "order": "date DESC",
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
        Fetch invoice PDF from Odoo using the Odoo 19 API.
        Returns PDF bytes that can be uploaded to WhatsApp.

        Uses ir.actions.report._get_report_from_name() and render_qweb_pdf()
        which is the recommended Odoo 19 approach.
        """
        try:
            # Odoo 19 API: Get the invoice report and render it to PDF
            # This uses the built-in account.report_invoice report

            logger.info(
                "Fetching invoice PDF using Odoo 19 API",
                extra={"invoice_id": invoice_id}
            )

            # Method 1: Try to get and render the standard invoice report
            report_names_to_try = [
                "account.report_invoice",
                "account.invoice_report",
            ]

            for report_name in report_names_to_try:
                try:
                    logger.info(
                        f"Searching for report",
                        extra={"invoice_id": invoice_id, "report_name": report_name}
                    )

                    try:
                        # Get the report action by name
                        report = self._execute(
                            "ir.actions.report",
                            "search_read",
                            [[["report_name", "=", report_name]]],
                            {"fields": ["id", "name", "report_name"]}
                        )

                        logger.info(
                            f"Report search result",
                            extra={"invoice_id": invoice_id, "report_name": report_name, "found": bool(report), "count": len(report) if report else 0}
                        )
                    except Exception as search_error:
                        logger.error(
                            f"Report search failed",
                            extra={"invoice_id": invoice_id, "report_name": report_name, "error": str(search_error)}
                        )

                        # Try to list all available reports for debugging
                        try:
                            logger.info("Attempting to list all available reports")
                            all_reports = self._execute(
                                "ir.actions.report",
                                "search_read",
                                [[]],
                                {"fields": ["id", "name", "report_name"], "limit": 20}
                            )
                            report_names = [r.get("report_name") for r in all_reports]
                            logger.info(
                                "All available reports",
                                extra={"invoice_id": invoice_id, "available_reports": report_names}
                            )
                        except Exception as list_error:
                            logger.error(f"Could not list reports: {str(list_error)}")

                        continue

                    if not report:
                        # Try to list all available reports for debugging
                        try:
                            logger.info("No reports found for that name, listing invoice-related reports")
                            all_reports = self._execute(
                                "ir.actions.report",
                                "search_read",
                                [[["report_name", "like", "invoice"]]],
                                {"fields": ["id", "name", "report_name"]}
                            )
                            report_names = [r.get("report_name") for r in all_reports]
                            logger.info(
                                "Available invoice-related reports",
                                extra={"invoice_id": invoice_id, "available_reports": report_names}
                            )
                        except Exception as e:
                            logger.error(f"Could not fetch available reports: {str(e)}")

                        continue

                    report_id = report[0]["id"]
                    logger.info(
                        f"Found report, attempting to render PDF",
                        extra={"invoice_id": invoice_id, "report_id": report_id, "report_name": report_name}
                    )

                    try:
                        # Render the report to PDF
                        pdf_content = self._execute(
                            "ir.actions.report",
                            "render_qweb_pdf",
                            [report_id, [invoice_id]],
                            {}
                        )

                        logger.info(
                            f"PDF render result",
                            extra={"invoice_id": invoice_id, "report_name": report_name, "has_content": bool(pdf_content), "type": type(pdf_content).__name__}
                        )
                    except Exception as render_error:
                        logger.error(
                            f"PDF render failed",
                            extra={"invoice_id": invoice_id, "report_name": report_name, "error": str(render_error)}
                        )
                        continue

                    if pdf_content:
                        # render_qweb_pdf returns [pdf_bytes, mime_type] or similar
                        if isinstance(pdf_content, list) and len(pdf_content) > 0:
                            pdf_data = pdf_content[0]
                        else:
                            pdf_data = pdf_content

                        # Handle base64 encoding if needed
                        if isinstance(pdf_data, str):
                            pdf_bytes = base64.b64decode(pdf_data)
                        elif isinstance(pdf_data, bytes):
                            pdf_bytes = pdf_data
                        else:
                            # If it's not bytes or string, try to convert
                            pdf_bytes = bytes(pdf_data) if pdf_data else b""

                        logger.info(
                            "Invoice PDF fetched via Odoo 19 API",
                            extra={"invoice_id": invoice_id, "report": report_name, "size": len(pdf_bytes)}
                        )
                        return pdf_bytes

                except Exception as e:
                    logger.debug(
                        f"Failed to fetch PDF using report {report_name}",
                        extra={"invoice_id": invoice_id, "error": str(e)}
                    )
                    continue

            # Method 2: Fallback - Try HTTP report endpoint
            logger.info(
                "Trying fallback HTTP report endpoint",
                extra={"invoice_id": invoice_id}
            )
            password = settings.ODOO_PASSWORD or settings.ODOO_API_KEY or ""
            report_url = f"{settings.ODOO_URL}/report/pdf/account.report_invoice/{invoice_id}"

            response = requests.get(
                report_url,
                auth=(settings.ODOO_USERNAME, password) if password else None,
                timeout=30,
                verify=True
            )

            # Check if we got HTML (error page) instead of PDF
            if response.content.startswith(b"<!DOCTYPE") or response.content.startswith(b"<html"):
                logger.debug(
                    "Got HTML response from report endpoint (likely auth failure)",
                    extra={"invoice_id": invoice_id, "status": response.status_code}
                )
            else:
                response.raise_for_status()

                # Verify it's a valid PDF
                if response.content.startswith(b"%PDF"):
                    logger.info(
                        "Invoice PDF fetched via HTTP report endpoint",
                        extra={"invoice_id": invoice_id, "size": len(response.content)}
                    )
                    return response.content

            logger.warning(
                "Failed to fetch PDF from Odoo, will try PDF generation fallback",
                extra={"invoice_id": invoice_id}
            )
            raise ValueError(
                f"Could not fetch valid PDF for invoice {invoice_id}. "
                "Tried account.report_invoice and HTTP endpoint."
            )

        except Exception as e:
            logger.error(
                "Failed to fetch invoice PDF from Odoo",
                extra={"invoice_id": invoice_id, "error": str(e)}
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

            # Details table
            details_data = [
                ["Invoice Number:", invoice_number],
                ["Invoice Date:", str(invoice_date)],
                ["Due Date:", str(due_date)],
                ["Amount:", f"₹{amount:,.2f}"],
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

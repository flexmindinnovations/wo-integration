import logging
import xmlrpc.client
from datetime import datetime
from sqlalchemy.orm import Session

from app.config import settings
from app.models.contact import Contact

logger = logging.getLogger(__name__)


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

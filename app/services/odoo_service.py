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

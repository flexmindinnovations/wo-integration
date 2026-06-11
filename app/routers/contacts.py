import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactOut, ContactUpdate, SyncResult
from app.services.odoo_service import OdooService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.post(
    "/sync",
    response_model=SyncResult,
    summary="Sync contacts from Odoo into local database",
)
def sync_contacts(db: Session = Depends(get_db)):
    """Pull all contacts from Odoo and sync to local database."""
    return OdooService().sync_contacts(db)


@router.post(
    "/",
    response_model=ContactOut,
    status_code=201,
    summary="Create a new contact in Odoo and local database",
)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db)):
    """
    Create a new contact in Odoo first, then store in local database.
    Returns the created contact.
    """
    try:
        odoo = OdooService()
        partner_id = odoo.create_partner(payload.name, payload.phone, payload.email)

        contact = Contact(
            name=payload.name,
            phone=payload.phone,
            email=payload.email,
            odoo_partner_id=partner_id,
            last_synced_at=datetime.utcnow(),
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)

        logger.info(
            "Contact created",
            extra={"contact_id": contact.id, "partner_id": partner_id, "name": payload.name},
        )
        return contact
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Failed to create contact", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to create contact in Odoo")


@router.get(
    "/",
    response_model=list[ContactOut],
    summary="List all locally stored contacts",
)
def list_contacts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all contacts from local database."""
    return db.query(Contact).offset(skip).limit(limit).all()


@router.get(
    "/{contact_id}",
    response_model=ContactOut,
    summary="Get a specific contact",
)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    """Get a specific contact by ID."""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail=f"Contact {contact_id} not found")
    return contact


@router.put(
    "/{contact_id}",
    response_model=ContactOut,
    summary="Update a contact in Odoo and local database",
)
def update_contact(contact_id: int, payload: ContactUpdate, db: Session = Depends(get_db)):
    """
    Update a contact in Odoo first, then update in local database.
    All fields are optional — only provided fields will be updated.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail=f"Contact {contact_id} not found")

    if not contact.odoo_partner_id:
        raise HTTPException(
            status_code=422,
            detail="Contact is not synced with Odoo (no partner_id)",
        )

    try:
        odoo = OdooService()
        odoo.update_partner(contact.odoo_partner_id, payload.name, payload.phone, payload.email)

        # Update local record
        if payload.name is not None:
            contact.name = payload.name
        if payload.phone is not None:
            contact.phone = payload.phone
        if payload.email is not None:
            contact.email = payload.email
        contact.last_synced_at = datetime.utcnow()

        db.commit()
        db.refresh(contact)

        logger.info(
            "Contact updated",
            extra={"contact_id": contact_id, "partner_id": contact.odoo_partner_id},
        )
        return contact
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Failed to update contact", extra={"contact_id": contact_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to update contact in Odoo")


@router.delete(
    "/{contact_id}",
    status_code=204,
    summary="Archive a contact in Odoo and remove from local database",
)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    """
    Archives the partner in Odoo (sets active=False) so history is preserved,
    then removes the local record.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail=f"Contact {contact_id} not found")

    # Archive in Odoo if linked
    if contact.odoo_partner_id:
        try:
            OdooService()._execute(
                "res.partner", "write",
                [[contact.odoo_partner_id], {"active": False}]
            )
        except Exception as e:
            logger.warning(
                "Could not archive partner in Odoo — deleting locally anyway",
                extra={"partner_id": contact.odoo_partner_id, "error": str(e)},
            )

    db.delete(contact)
    db.commit()
    logger.info("Contact deleted", extra={"contact_id": contact_id})

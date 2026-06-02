from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.contact import Contact
from app.schemas.contact import ContactOut, SyncResult
from app.services.odoo_service import OdooService

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.post(
    "/sync",
    response_model=SyncResult,
    summary="Sync contacts from Odoo into local database",
)
def sync_contacts(db: Session = Depends(get_db)):
    return OdooService().sync_contacts(db)


@router.get(
    "/",
    response_model=list[ContactOut],
    summary="List all locally stored contacts",
)
def list_contacts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Contact).offset(skip).limit(limit).all()

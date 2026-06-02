from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ContactOut(BaseModel):
    id: int
    name: str
    phone: str
    email: Optional[str] = None
    odoo_partner_id: Optional[int] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncResult(BaseModel):
    created: int
    updated: int
    skipped: int
    total: int

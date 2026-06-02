from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Contact name")
    phone: str = Field(..., min_length=1, description="Phone number (digits only, will be normalized)")
    email: Optional[str] = Field(None, max_length=255, description="Email address")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Mohammad Imran",
                "phone": "918446998579",
                "email": "imran@example.com"
            }
        }
    )


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, min_length=1)
    email: Optional[str] = Field(None, max_length=255)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Mohammad Imran Updated",
                "phone": "918446998579"
            }
        }
    )


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

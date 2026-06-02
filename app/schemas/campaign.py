from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.models.campaign import CampaignStatus
from app.models.campaign_message import DeliveryStatus


class CampaignCreate(BaseModel):
    name: str
    topic: Optional[str] = None
    template_name: str
    scheduled_at: Optional[datetime] = None


class CampaignOut(BaseModel):
    id: int
    name: str
    topic: Optional[str] = None
    template_name: str
    status: CampaignStatus
    scheduled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CampaignMessageOut(BaseModel):
    id: int
    campaign_id: int
    contact_id: int
    whatsapp_message_id: Optional[str] = None
    delivery_status: DeliveryStatus
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CampaignAnalytics(BaseModel):
    campaign_id: int
    campaign_name: str
    status: CampaignStatus
    total_contacts: int
    pending: int
    sent: int
    delivered: int
    read: int
    failed: int
    delivery_rate: float
    read_rate: float

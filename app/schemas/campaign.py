from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict
from app.models.campaign import CampaignStatus
from app.models.campaign_message import DeliveryStatus


class CampaignCreate(BaseModel):
    name: str
    topic: Optional[str] = None
    template_name: str
    template_language: str = "en"
    template_components: Optional[list[dict[str, Any]]] = None
    scheduled_at: Optional[datetime] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Payment Reminder June",
                "topic": "Outstanding Invoice Reminder",
                "template_name": "payment_reminder",
                "template_language": "en",
                "template_components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": "{{contact_name}}"},
                            {"type": "text", "text": "INR"},
                            {"type": "text", "text": "1500"},
                            {"type": "text", "text": "Flexmind Innovations"},
                        ],
                    }
                ],
            }
        }
    )


class CampaignOut(BaseModel):
    id: int
    name: str
    topic: Optional[str] = None
    template_name: str
    template_language: Optional[str] = None
    template_components: Optional[list[dict[str, Any]]] = None
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

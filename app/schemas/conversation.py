from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.models.conversation_message import MessageRole


class ConversationMessageOut(BaseModel):
    id: int
    contact_phone: str
    role: MessageRole
    content: str
    wamid: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationSummary(BaseModel):
    contact_phone: str
    last_message: str
    last_role: MessageRole
    last_message_at: datetime
    message_count: int

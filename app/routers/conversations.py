import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.conversation_message import ConversationMessage, MessageRole
from app.schemas.conversation import ConversationMessageOut, ConversationSummary
from app.services.ws_manager import manager
from app.services.ai_pipeline import process_ai_reply, serialize_message

router = APIRouter(prefix="/conversations", tags=["Conversations"])
logger = logging.getLogger(__name__)


class MessagePayload(BaseModel):
    content: str


@router.get(
    "/",
    response_model=list[ConversationSummary],
    summary="List all conversations with their last message",
)
def list_conversations(db: Session = Depends(get_db)):
    latest_subq = (
        db.query(
            ConversationMessage.contact_phone,
            func.max(ConversationMessage.created_at).label("max_created_at"),
            func.count(ConversationMessage.id).label("message_count"),
        )
        .group_by(ConversationMessage.contact_phone)
        .subquery()
    )

    rows = (
        db.query(
            ConversationMessage,
            latest_subq.c.message_count,
        )
        .join(
            latest_subq,
            (ConversationMessage.contact_phone == latest_subq.c.contact_phone)
            & (ConversationMessage.created_at == latest_subq.c.max_created_at),
        )
        .order_by(ConversationMessage.created_at.desc())
        .all()
    )

    return [
        ConversationSummary(
            contact_phone=msg.contact_phone,
            last_message=msg.content,
            last_role=msg.role,
            last_message_at=msg.created_at,
            message_count=count,
        )
        for msg, count in rows
    ]


@router.get(
    "/{phone}",
    response_model=list[ConversationMessageOut],
    summary="Full message history for a phone number",
)
def get_conversation(
    phone: str,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.contact_phone == phone)
        .order_by(ConversationMessage.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    if not messages and skip == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No conversation found for phone {phone}",
        )
    return messages


@router.post(
    "/{phone}/message",
    response_model=ConversationMessageOut,
    summary="Send a message and get an AI reply (real WhatsApp pipeline)",
)
async def send_chat_message(
    phone: str,
    payload: MessagePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Saves the message as an inbound customer message (role=user) and triggers
    the full AI pipeline: Odoo context fetch → Gemini reply → WhatsApp delivery
    → WebSocket broadcast. This is the same pipeline the real WhatsApp webhook uses.
    """
    msg = ConversationMessage(
        contact_phone=phone,
        role=MessageRole.user,
        content=payload.content,
        wamid=None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    background_tasks.add_task(process_ai_reply, phone, payload.content)
    logger.info("Chat message received", extra={"phone": phone})
    return msg

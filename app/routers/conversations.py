import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.conversation_message import ConversationMessage
from app.schemas.conversation import ConversationMessageOut, ConversationSummary

router = APIRouter(prefix="/conversations", tags=["Conversations"])
logger = logging.getLogger(__name__)


@router.get(
    "/",
    response_model=list[ConversationSummary],
    summary="List all conversations with their last message",
)
def list_conversations(db: Session = Depends(get_db)):
    """
    Return one summary row per unique phone number, showing the most recent
    message content, role, timestamp, and total message count.
    """
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
    """
    Return all messages for a given phone number, oldest first.
    Supports pagination with skip/limit.
    Returns 404 if no conversation exists for that phone.
    """
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

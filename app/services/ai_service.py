import logging
from sqlalchemy.orm import Session
import anthropic

from app.config import settings
from app.models.conversation_message import ConversationMessage, MessageRole

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful, friendly assistant communicating via WhatsApp. "
    "Keep responses concise and conversational. "
    "Answer questions clearly and helpfully. "
    "If you are unsure about something, say so honestly."
)

_CONTEXT_WINDOW = 10


class AiService:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def generate_reply(self, phone: str, db: Session) -> str:
        """
        Fetch the last _CONTEXT_WINDOW messages for `phone`, build the
        Claude messages list, call the API, and return the reply text.

        Raises on API failure — callers must handle exceptions.
        """
        history = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.contact_phone == phone)
            .order_by(ConversationMessage.created_at.desc())
            .limit(_CONTEXT_WINDOW)
            .all()
        )
        # Reverse so oldest-first (chronological) order for the API
        history = list(reversed(history))

        messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in history
        ]

        response = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )

        reply: str = response.content[0].text
        logger.info(
            "AI reply generated",
            extra={"phone": phone, "input_tokens": response.usage.input_tokens},
        )
        return reply

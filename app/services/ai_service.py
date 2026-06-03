import logging
from sqlalchemy.orm import Session
import google.generativeai as genai

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
        genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
        self._model = genai.GenerativeModel("gemini-2.5-flash")

    def generate_reply(self, phone: str, db: Session) -> str:
        """
        Fetch the last _CONTEXT_WINDOW messages for `phone`, build the
        Gemini messages list, call the API, and return the reply text.

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

        # Build conversation history for Gemini
        # Gemini expects: [{"role": "user"/"model", "parts": [{"text": "..."}]}]
        messages = []
        for msg in history:
            role = "user" if msg.role.value == "user" else "model"
            messages.append({
                "role": role,
                "parts": [{"text": msg.content}]
            })

        # Start a chat session with system instruction
        chat = self._model.start_chat(history=messages)

        response = chat.send_message(
            _SYSTEM_PROMPT,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=1024,
            ),
        )

        reply: str = response.text
        logger.info(
            "AI reply generated",
            extra={"phone": phone, "model": "gemini-2.5-flash"},
        )
        return reply

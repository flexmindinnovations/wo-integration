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

    def generate_reply_with_context(
        self,
        phone: str,
        db: Session,
        contact=None,
        odoo_context: dict | None = None
    ) -> str:
        """
        Generate AI reply with Odoo business context.
        If odoo_context is provided, enriches system prompt with customer data.
        Falls back to generic reply if context is unavailable.
        """
        history = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.contact_phone == phone)
            .order_by(ConversationMessage.created_at.desc())
            .limit(_CONTEXT_WINDOW)
            .all()
        )
        history = list(reversed(history))

        messages = [
            {"role": "user" if msg.role.value == "user" else "model",
             "parts": [{"text": msg.content}]}
            for msg in history
        ]

        system_prompt = self._build_context_aware_prompt(contact, odoo_context)

        chat = self._model.start_chat(history=messages)
        response = chat.send_message(
            system_prompt,
            generation_config=genai.types.GenerationConfig(max_output_tokens=1024),
        )

        reply: str = response.text
        has_context = odoo_context is not None and (odoo_context.get("invoices") or odoo_context.get("orders"))
        logger.info(
            "AI reply generated with context",
            extra={"phone": phone, "has_odoo_context": has_context},
        )
        return reply

    def _build_context_aware_prompt(self, contact, odoo_context: dict | None) -> str:
        """Build system prompt enriched with customer data from Odoo."""
        if not odoo_context:
            return _SYSTEM_PROMPT

        # Check if we have any business data
        has_invoices = odoo_context.get("invoices")
        has_orders = odoo_context.get("orders")
        has_payments = odoo_context.get("payments")
        has_any_business_data = has_invoices or has_orders or has_payments

        prompt = (
            f"You are a helpful customer service assistant for Flexmind Innovations. "
            f"You're helping {contact.name if contact else 'a customer'}.\n\n"
        )

        # Only add business data section if we have data
        if has_any_business_data:
            if has_invoices:
                prompt += "Outstanding Invoices:\n"
                for inv in odoo_context["invoices"][:3]:
                    due = inv.get("due_date", "N/A")
                    amount = inv.get("amount_total", 0)
                    state = inv.get("payment_state", "unknown")
                    prompt += f"  • {inv['name']}: ₹{amount:.2f} (Due: {due}, Status: {state})\n"
                prompt += "\n"

            if has_orders:
                prompt += "Recent Orders:\n"
                for order in odoo_context["orders"][:3]:
                    state = order.get("state", "unknown")
                    amount = order.get("amount_total", 0)
                    date = order.get("date_order", "N/A")
                    prompt += f"  • {order['name']}: ₹{amount:.2f} ({state}, {date})\n"
                prompt += "\n"

            if has_payments:
                payment = odoo_context["payments"][0] if odoo_context["payments"] else None
                if payment:
                    prompt += f"Last Payment: {payment['payment_date']} (₹{payment.get('amount', 0):.2f})\n\n"

            prompt += (
                "Use this account information to provide personalized, helpful responses. "
                "Be concise for WhatsApp (short paragraphs). "
                "Offer solutions based on their account status. "
                "If you need more information, ask politely. "
                "If unsure, be honest."
            )
        else:
            # No business data available - use friendly alternative
            prompt += (
                "This customer's business records are not currently accessible in our system, "
                "so you won't have specific invoice or order details to reference. "
                "Be helpful and friendly. If they ask about specific orders or invoices, "
                "politely explain that you can't access those details and suggest they check "
                "their account directly or contact our support team. Be concise for WhatsApp."
            )

        return prompt

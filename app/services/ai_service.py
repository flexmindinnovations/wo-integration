import logging
from typing import cast
from sqlalchemy.orm import Session
from google import genai
from google.genai.types import ContentDict, ContentListUnionDict, PartDict

from app.config import settings
from app.models.conversation_message import ConversationMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful, friendly customer service assistant communicating via WhatsApp. "
    "Understand exactly what the customer is asking and respond to that — nothing more, nothing less. "
    "Keep responses concise and conversational. "
    "If you are unsure about something, say so honestly."
)

_CONTEXT_WINDOW = 10


class AiService:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

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
        messages: list[ContentDict] = []
        for msg in history:
            role = "user" if msg.role.value == "user" else "model"
            messages.append(ContentDict(
                role=role,
                parts=[PartDict(text=msg.content)],
            ))

        contents: ContentListUnionDict = cast(ContentListUnionDict, messages)

        response = self._client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config={
                "max_output_tokens": 1024,
                "system_instruction": _SYSTEM_PROMPT,
            }
        )

        reply = response.text or ""
        if not reply and response.parts:
            first_part = response.parts[0]
            reply = first_part.text or ""
        logger.info(
            "AI reply generated",
            extra={"phone": phone, "model": settings.GEMINI_MODEL},
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

        messages: list[ContentDict] = [
            ContentDict(
                role="user" if msg.role.value == "user" else "model",
                parts=[PartDict(text=msg.content)],
            )
            for msg in history
        ]

        system_prompt = self._build_context_aware_prompt(contact, odoo_context)

        contents: ContentListUnionDict = cast(ContentListUnionDict, messages)

        response = self._client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config={
                "max_output_tokens": 1024,
                "system_instruction": system_prompt,
            }
        )

        reply = response.text or ""
        if not reply and response.parts:
            first_part = response.parts[0]
            reply = first_part.text or ""
        has_invoices = odoo_context is not None and odoo_context.get("invoices")
        has_orders = odoo_context is not None and odoo_context.get("orders")
        access_success = odoo_context.get("access_success", False) if odoo_context else False
        logger.info(
            "AI reply generated with context",
            extra={
                "phone": phone,
                "odoo_access_success": access_success,
                "has_invoices": bool(has_invoices),
                "has_orders": bool(has_orders),
                "invoice_count": len(odoo_context.get("invoices", [])) if odoo_context else 0,
                "full_invoices": odoo_context.get("invoices", []) if odoo_context else [],
            },
        )
        return reply

    def _build_context_aware_prompt(self, contact, odoo_context: dict | None) -> str:
        """Build system prompt enriched with customer data from Odoo."""
        if not odoo_context:
            return _SYSTEM_PROMPT

        # Check if Odoo fetch succeeded
        access_success = odoo_context.get("access_success", False)
        has_invoices = odoo_context.get("invoices")
        has_orders = odoo_context.get("orders")
        has_payments = odoo_context.get("payments")
        has_any_business_data = has_invoices or has_orders or has_payments

        prompt = (
            f"You are a helpful customer service assistant for Flexmind Innovations. "
            f"You're helping {contact.name if contact else 'a customer'}.\n\n"
        )

        # Case 1: Odoo access succeeded and has data
        if access_success and has_any_business_data:
            if has_invoices:
                prompt += f"INVOICES ({len(odoo_context['invoices'])} total):\n"
                for inv in odoo_context["invoices"][:10]:
                    date = inv.get("invoice_date") or inv.get("due_date") or "N/A"
                    amount = inv.get("amount_total", 0)
                    state = inv.get("payment_state", "unknown").replace("_", " ")
                    name = inv.get("name", "Unknown")
                    prompt += f"  • {name}: ₹{amount:.2f} (Date: {date}, Status: {state})\n"
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
                    payment_date = payment.get('date') or payment.get('payment_date', 'N/A')
                    prompt += f"Last Payment: {payment_date} (₹{payment.get('amount', 0):.2f})\n\n"

            prompt += (
                "Use the account data above to give accurate, personalized answers. "
                "Be concise for WhatsApp — short and direct. "
                "Read the customer's message carefully and respond to exactly what they asked. "
                "A simple question deserves a simple answer; a detailed question deserves detail. "
                "Only mention sending a PDF if the customer explicitly asked for one. "
                "Do not add unsolicited suggestions or extra information. "
                "If unsure, be honest."
            )
        # Case 2: Odoo access succeeded but no data found
        elif access_success and not has_any_business_data:
            prompt += (
                "I checked the customer's account and they don't have any invoices, orders, or payments yet. "
                "Be helpful and friendly. If they ask about ordering or invoicing, let them know they can "
                "create an order on the website or contact sales. Be concise for WhatsApp."
            )
        # Case 3: Odoo access failed
        else:
            prompt += (
                "I'm temporarily unable to access the customer's account details in our system. "
                "Be helpful and friendly anyway. If they ask about specific orders or invoices, "
                "explain that you can't retrieve those details right now and suggest they try again "
                "in a few moments or contact our support team. Be concise for WhatsApp."
            )

        return prompt

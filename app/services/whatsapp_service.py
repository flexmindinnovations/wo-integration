import logging
import requests
from app.config import settings

logger = logging.getLogger(__name__)

_GRAPH_API_BASE = "https://graph.facebook.com/v25.0"


class WhatsAppService:
    def __init__(self) -> None:
        self._phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self._token = settings.WHATSAPP_TOKEN
        self._url = f"{_GRAPH_API_BASE}/{self._phone_number_id}/messages"
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def send_template(
        self,
        phone: str,
        template_name: str,
        language_code: str = "en",
        components: list[dict] | None = None,
    ) -> dict:
        phone = "".join(ch for ch in phone if ch.isdigit())

        payload: dict = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components

        response = requests.post(self._url, headers=self._headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        logger.info(
            "WhatsApp template sent",
            extra={"phone": phone, "template": template_name},
        )
        return data

    def send_text(self, phone: str, text: str) -> dict:
        """
        Send a free-form text reply.

        AI extension point: called by the future AI reply handler after
        generating a response from an incoming WhatsApp message.
        """
        phone = "".join(ch for ch in phone if ch.isdigit())
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        }
        response = requests.post(self._url, headers=self._headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

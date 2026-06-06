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
        self._media_url = f"{_GRAPH_API_BASE}/{self._phone_number_id}/media"
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

    def upload_media(self, file_bytes: bytes, filename: str, mimetype: str = "application/pdf") -> str:
        """
        Upload a file to Meta and return the media ID.

        Args:
            file_bytes: File content as bytes
            filename: Filename for the upload
            mimetype: MIME type (default: application/pdf)

        Returns:
            Media ID from Meta's API
        """
        try:
            # Determine media type from mimetype
            if "pdf" in mimetype.lower():
                media_type = "document"
            elif "image" in mimetype.lower():
                media_type = "image"
            elif "audio" in mimetype.lower():
                media_type = "audio"
            elif "video" in mimetype.lower():
                media_type = "video"
            else:
                media_type = "document"

            # Meta API requires both files and data parameters
            files = {
                "file": (filename, file_bytes, mimetype),
            }
            data = {
                "messaging_product": "whatsapp",
                "type": media_type,
            }
            headers = {
                "Authorization": f"Bearer {self._token}",
            }

            logger.info(
                "Uploading media to Meta",
                extra={"filename": filename, "size": len(file_bytes), "mimetype": mimetype, "type": media_type}
            )

            response = requests.post(
                self._media_url,
                files=files,
                data=data,
                headers=headers,
                timeout=60
            )

            if not response.ok:
                error_detail = response.text
                logger.error(
                    "Media upload failed",
                    extra={
                        "filename": filename,
                        "status": response.status_code,
                        "error": error_detail
                    }
                )
                response.raise_for_status()

            data = response.json()
            media_id = data.get("id")
            logger.info(
                "Media uploaded to Meta successfully",
                extra={"filename": filename, "media_id": media_id}
            )
            return media_id

        except Exception as e:
            logger.error(
                "Exception during media upload",
                extra={"filename": filename, "error": str(e)}
            )
            raise

    def send_document_by_id(self, phone: str, media_id: str, filename: str | None = None) -> dict:
        """
        Send a document/file to user using uploaded media ID.

        Args:
            phone: WhatsApp phone number
            media_id: Media ID from upload_media()
            filename: Optional filename to display
        """
        phone = "".join(ch for ch in phone if ch.isdigit())
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "document",
            "document": {
                "id": media_id,
            },
        }
        if filename:
            payload["document"]["caption"] = filename

        response = requests.post(self._url, headers=self._headers, json=payload, timeout=30)
        response.raise_for_status()
        logger.info(
            "WhatsApp document sent",
            extra={"phone": phone, "filename": filename, "media_id": media_id},
        )
        return response.json()

    def send_document(self, phone: str, file_url: str, filename: str | None = None) -> dict:
        """
        Send a document/file to user via URL.

        Args:
            phone: WhatsApp phone number
            file_url: URL to the file (public URL)
            filename: Optional filename to display (e.g., "invoice.pdf")
        """
        phone = "".join(ch for ch in phone if ch.isdigit())
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "document",
            "document": {
                "link": file_url,
            },
        }
        if filename:
            payload["document"]["caption"] = filename

        response = requests.post(self._url, headers=self._headers, json=payload, timeout=30)
        response.raise_for_status()
        logger.info(
            "WhatsApp document sent via URL",
            extra={"phone": phone, "filename": filename},
        )
        return response.json()

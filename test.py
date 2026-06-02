"""Quick smoke-test: send a single WhatsApp template message."""
from dotenv import load_dotenv
from app.services.whatsapp_service import WhatsAppService

load_dotenv()

svc = WhatsAppService()
response = svc.send_template(
    phone="918446998579",
    template_name="payment_reminder",
    components=[
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Test User"},
                {"type": "text", "text": "INR"},
                {"type": "text", "text": "0"},
                {"type": "text", "text": "Flexmind Innovations"},
            ],
        }
    ],
)
print(response)

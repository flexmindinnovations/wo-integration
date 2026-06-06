# Updated get_invoice_pdf() method for OdooService
# Replace the entire method in app/services/odoo_service.py with this version

def get_invoice_pdf(self, invoice_id: int) -> bytes:
    """
    Fetch invoice PDF from Odoo via custom API endpoint with token authentication.

    This uses the custom 'whatsapp_invoice_api' module installed in Odoo,
    which provides secure token-based PDF retrieval.

    Args:
        invoice_id: The Odoo invoice ID

    Returns:
        PDF bytes that can be uploaded to WhatsApp
    """
    try:
        # Use custom API endpoint with token authentication
        api_token = settings.ODOO_API_KEY  # Reuse API key as token
        api_url = f"{settings.ODOO_URL}/api/invoice/pdf/{invoice_id}"

        logger.info(
            "Fetching invoice PDF via custom Odoo API endpoint",
            extra={"invoice_id": invoice_id, "endpoint": "/api/invoice/pdf/"}
        )

        response = requests.get(
            api_url,
            params={"token": api_token},
            timeout=30,
            verify=True,
            headers={"Accept": "application/pdf"}
        )

        # Handle different error cases
        if response.status_code == 401:
            logger.error(
                "API authentication failed - token is invalid or expired",
                extra={"invoice_id": invoice_id}
            )
            raise ValueError(
                "Odoo API token invalid. Ensure the custom module is installed "
                "and the API token is correct."
            )

        if response.status_code == 404:
            logger.warning(
                "Invoice not found in Odoo",
                extra={"invoice_id": invoice_id}
            )
            raise ValueError(f"Invoice {invoice_id} not found in Odoo")

        if response.status_code == 400:
            logger.warning(
                "Bad request to API",
                extra={"invoice_id": invoice_id, "response": response.text}
            )
            raise ValueError(f"Invalid invoice request: {response.text}")

        if response.status_code != 200:
            logger.error(
                "Unexpected API response",
                extra={
                    "invoice_id": invoice_id,
                    "status": response.status_code,
                    "response": response.text[:200]
                }
            )
            raise ValueError(
                f"Failed to fetch PDF from Odoo API (status {response.status_code})"
            )

        # Verify it's a valid PDF
        if not response.content.startswith(b"%PDF"):
            logger.error(
                "Response is not a valid PDF",
                extra={"invoice_id": invoice_id, "first_bytes": response.content[:20]}
            )
            raise ValueError("Odoo returned invalid PDF content")

        logger.info(
            "Invoice PDF fetched successfully from Odoo API",
            extra={
                "invoice_id": invoice_id,
                "size": len(response.content),
                "source": "odoo_api"
            }
        )

        return response.content

    except requests.exceptions.ConnectionError as e:
        logger.error(
            "Failed to connect to Odoo API",
            extra={"invoice_id": invoice_id, "error": str(e)}
        )
        raise ValueError(f"Cannot reach Odoo instance: {str(e)}")

    except requests.exceptions.Timeout:
        logger.error(
            "Odoo API request timed out",
            extra={"invoice_id": invoice_id}
        )
        raise ValueError("Odoo API request timed out")

    except Exception as e:
        logger.error(
            "Failed to fetch invoice PDF from Odoo API",
            extra={"invoice_id": invoice_id, "error": str(e)}
        )
        raise

import logging
from odoo import http, fields
from odoo.exceptions import AccessDenied, NotFound
from werkzeug.exceptions import Unauthorized

_logger = logging.getLogger(__name__)

class WhatsAppInvoiceAPI(http.Controller):
    """API endpoint for WhatsApp invoice PDF retrieval with token authentication"""

    def _validate_api_token(self, token):
        """Validate API token and return user"""
        if not token:
            raise Unauthorized("API token is required")

        # Search for user with matching api_token
        env = http.request.env
        user = env['res.users'].sudo().search([
            ('api_token', '=', token),
            ('active', '=', True)
        ], limit=1)

        if not user:
            _logger.warning(f"Invalid API token attempted: {token[:10]}...")
            raise Unauthorized("Invalid API token")

        return user

    @http.route('/api/invoice/pdf/<int:invoice_id>', type='http', auth='public', csrf=False)
    def get_invoice_pdf(self, invoice_id, **kwargs):
        """
        Get invoice PDF via API token.

        Usage:
        GET /api/invoice/pdf/3?token=YOUR_API_TOKEN

        Returns: PDF file with proper headers
        """
        try:
            token = kwargs.get('token')
            user = self._validate_api_token(token)

            # Get the invoice with user context
            invoice = http.request.env['account.move'].sudo(user).browse(invoice_id)

            if not invoice:
                _logger.warning(f"Invoice {invoice_id} not found")
                raise NotFound(f"Invoice {invoice_id} not found")

            if invoice.state != 'posted':
                _logger.warning(f"Invoice {invoice_id} is not in posted state: {invoice.state}")
                return http.request.make_response(
                    "Error: Invoice must be in posted state",
                    status=400
                )

            # Generate PDF report
            report = http.request.env['ir.actions.report'].sudo().search([
                ('report_name', '=', 'account.report_invoice')
            ], limit=1)

            if not report:
                _logger.error("Invoice report 'account.report_invoice' not found")
                return http.request.make_response(
                    "Error: Invoice report template not found",
                    status=500
                )

            # Render PDF
            try:
                pdf_content, _ = report.sudo()._render_qweb_pdf([invoice.id])
            except Exception as e:
                _logger.error(f"Failed to render invoice PDF: {str(e)}")
                return http.request.make_response(
                    f"Error: Could not render PDF - {str(e)}",
                    status=500
                )

            # Return PDF with proper headers
            response = http.request.make_response(pdf_content)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename="{invoice.name}.pdf"'
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'

            _logger.info(f"Invoice {invoice_id} PDF generated successfully for user {user.name}")
            return response

        except Unauthorized as e:
            return http.request.make_response(
                f"Unauthorized: {str(e)}",
                status=401,
                headers=[('Content-Type', 'application/json')]
            )
        except NotFound as e:
            return http.request.make_response(
                f"Not Found: {str(e)}",
                status=404,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            _logger.exception(f"Unexpected error in invoice PDF API: {str(e)}")
            return http.request.make_response(
                f"Error: {str(e)}",
                status=500,
                headers=[('Content-Type', 'application/json')]
            )

    @http.route('/api/invoice/pdf/test', type='http', auth='public', csrf=False)
    def test_api(self, **kwargs):
        """Test endpoint to verify API is working"""
        token = kwargs.get('token')

        if not token:
            return http.request.make_response(
                "Error: token parameter is required\nUsage: /api/invoice/pdf/test?token=YOUR_TOKEN",
                status=400
            )

        try:
            user = self._validate_api_token(token)
            return http.request.make_response(
                f"Success! API is working. Authenticated as: {user.name}"
            )
        except Unauthorized as e:
            return http.request.make_response(
                f"Error: {str(e)}",
                status=401
            )

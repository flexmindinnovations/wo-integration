# WhatsApp Invoice API Module - Installation Guide

## Step 1: Create Module in Odoo

### On Odoo SaaS via File Manager:

1. Go to **Settings → Tools → Code Editor** (or check your Odoo admin panel for file access)
2. Navigate to your **addons** folder
3. Create a new folder: `whatsapp_invoice_api`
4. Inside that folder, create these files:

```
whatsapp_invoice_api/
├── __init__.py                    (copy content from whatsapp_invoice_api_init.py)
├── __manifest__.py                (copy content from whatsapp_invoice_api_manifest.py)
├── controllers/
│   ├── __init__.py                (copy content from whatsapp_invoice_api_controllers_init.py)
│   └── main.py                    (copy content from whatsapp_invoice_api_controller.py)
└── security/
    └── ir.model.access.csv        (copy content from whatsapp_invoice_api_access.csv)
```

### File Contents:

#### `__manifest__.py`
```python
{
    'name': 'WhatsApp Invoice API',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Token-based API endpoint for generating invoice PDFs',
    'author': 'Your Company',
    'depends': ['account', 'sale'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
}
```

#### `__init__.py`
```python
from . import controllers
```

#### `controllers/__init__.py`
```python
from . import main
```

#### `controllers/main.py`
[Use the full controller code provided above]

#### `security/ir.model.access.csv`
```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_account_move_whatsapp_api,Access account.move for WhatsApp API,account.model_account_move,,1,0,0,0
```

---

## Step 2: Install Module in Odoo

1. Go to **Apps** menu
2. Click **Update Apps List** (top right corner)
3. Search for `whatsapp_invoice_api`
4. Click **Install**

---

## Step 3: Generate API Token

### Option A: Create a New User for API Access (Recommended)

1. Go to **Settings → Users & Companies → Users**
2. Create a new user:
   - Name: "WhatsApp API User"
   - Email: "whatsapp-api@yourcompany.com"
   - Login: "whatsapp_api"
   - Password: (strong random password)
   - Access Rights: 
     - ✅ Accounting (minimal read access)
     - ✅ Sales (minimal read access)

### Option B: Use Existing User

Use any existing user that has access to view invoices.

### Get API Token:

1. **In Odoo 19**, API tokens are generated differently. Use this workaround:
   - Edit the user in the database or use a custom field
   - Or use a simple token generation script

2. **Quick Solution** - Create a simple token in Odoo:
   - Go to the user record
   - In the bottom of the form, look for or add field: `api_token`
   - Generate a random token (example: `whatsapp_api_token_abc123xyz789`)

---

## Step 4: Update Your Python Code

Update the `get_invoice_pdf()` method in your WhatsApp service:

```python
def get_invoice_pdf(self, invoice_id: int) -> bytes:
    """
    Fetch invoice PDF from Odoo via custom API endpoint.
    Uses token-based authentication.
    """
    try:
        # Use the custom API endpoint instead of RPC
        api_token = settings.ODOO_API_KEY  # Reuse your API key as token
        api_url = f"{settings.ODOO_URL}/api/invoice/pdf/{invoice_id}"

        logger.info(
            "Fetching invoice PDF via custom API endpoint",
            extra={"invoice_id": invoice_id, "url": api_url}
        )

        response = requests.get(
            api_url,
            params={"token": api_token},
            timeout=30,
            verify=True
        )

        if response.status_code == 401:
            logger.error("API authentication failed - check token", extra={"invoice_id": invoice_id})
            raise ValueError("API token is invalid or expired")

        if response.status_code == 404:
            logger.warning("Invoice not found in Odoo", extra={"invoice_id": invoice_id})
            raise ValueError(f"Invoice {invoice_id} not found")

        if response.status_code != 200:
            logger.error(
                "API request failed",
                extra={"invoice_id": invoice_id, "status": response.status_code, "response": response.text}
            )
            raise ValueError(f"Failed to fetch PDF: {response.text}")

        # Verify it's a valid PDF
        if not response.content.startswith(b"%PDF"):
            logger.error("Response is not a valid PDF", extra={"invoice_id": invoice_id})
            raise ValueError("Invalid PDF response from API")

        logger.info(
            "Invoice PDF fetched successfully via API",
            extra={"invoice_id": invoice_id, "size": len(response.content)}
        )

        return response.content

    except requests.exceptions.RequestException as e:
        logger.error(
            "API request failed",
            extra={"invoice_id": invoice_id, "error": str(e)}
        )
        raise ValueError(f"Failed to fetch PDF from API: {str(e)}")

    except Exception as e:
        logger.error(
            "Failed to fetch invoice PDF",
            extra={"invoice_id": invoice_id, "error": str(e)}
        )
        raise
```

---

## Step 5: Test the API

### Test Endpoint (Before Using in Production):

```bash
curl "https://your-odoo-instance.odoo.com/api/invoice/pdf/test?token=YOUR_API_TOKEN"
```

Expected response:
```
Success! API is working. Authenticated as: WhatsApp API User
```

### Test PDF Retrieval:

```bash
curl "https://your-odoo-instance.odoo.com/api/invoice/pdf/3?token=YOUR_API_TOKEN" \
  --output invoice.pdf
```

---

## Step 6: Deploy Updated Code

1. Replace the `get_invoice_pdf()` method in `app/services/odoo_service.py`
2. Commit and push changes
3. Deploy to Render

---

## Troubleshooting

### Error: "Invalid API token"
- Check that the token is correct
- Make sure the user account is active

### Error: "Invoice report template not found"
- Verify `account` module is installed in Odoo
- Check if report `account.report_invoice` exists

### Error: "Could not render PDF"
- Invoice might not be in "posted" state
- Try generating the PDF manually in Odoo first to ensure it works

### Error: 404 Not Found
- Verify invoice ID exists
- Check that the user has permission to view that invoice

---

## Security Notes

✅ **Token-based authentication** - Only valid API token can access
✅ **User context** - PDFs are generated with user's permissions
✅ **No database changes** - Safe, read-only operation
✅ **Proper headers** - Cache control and content-type set correctly

---

## Next Steps

After installation and testing:

1. Update your WhatsApp service code (Step 4)
2. Redeploy your Python application
3. Send a test WhatsApp message with "invoice"
4. You should now get the **Odoo-generated professional invoice PDF** instead of the generated one!

---

## Need Help?

If you encounter issues:
1. Check Odoo logs: **Settings → Technical → Logs**
2. Test the API endpoint directly with curl
3. Verify module is installed: **Apps** menu shows it as installed

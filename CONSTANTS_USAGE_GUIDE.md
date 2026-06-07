# Constants Usage Guide

## Overview

All application constants have been centralized in **`app/constants.py`** - a single source of truth for all magic strings, numbers, and configuration values.

**Benefits:**
- ✅ No hardcoded values scattered throughout the codebase
- ✅ Easy to update values globally by changing one place
- ✅ Self-documenting code with clear constant names
- ✅ Consistent naming and organization
- ✅ Type-safe with organized constant classes

---

## Quick Start

### Import Constants

```python
from app.constants import (
    OdooModels,
    OdooFieldsInvoice,
    ApiTimeouts,
    InvoiceDefaults,
    WhatsAppApi
)
```

### Use Instead of Hardcoded Values

❌ **Before (Hardcoded):**
```python
invoices = self._execute(
    "account.move",
    "search_read",
    [[]],
    {"fields": ["id", "name", "amount_total"], "limit": 5}
)
```

✅ **After (Using Constants):**
```python
from app.constants import OdooModels, OdooFieldsInvoice, ApiDefaults

invoices = self._execute(
    OdooModels.ACCOUNT_MOVE,
    OdooActions.SEARCH_READ,
    [[]],
    {
        "fields": [OdooFieldsInvoice.ID, OdooFieldsInvoice.NAME, OdooFieldsInvoice.AMOUNT_TOTAL],
        "limit": ApiDefaults.INVOICE_LIMIT
    }
)
```

---

## Constant Classes Reference

### 1. **Odoo Models** (`OdooModels`)

Models used in Odoo XML-RPC calls.

```python
from app.constants import OdooModels

OdooModels.ACCOUNT_MOVE          # "account.move" - Invoices (Odoo 19+)
OdooModels.ACCOUNT_INVOICE       # "account.invoice" - Invoices (older versions)
OdooModels.RES_PARTNER           # "res.partner" - Contacts
OdooModels.SALE_ORDER            # "sale.order" - Sales orders
OdooModels.ACCOUNT_PAYMENT       # "account.payment" - Payments
OdooModels.ACCOUNT_MOVE_LINE     # "account.move.line" - Invoice lines
```

### 2. **Odoo Fields** (By Model)

Field names for each Odoo model.

```python
from app.constants import OdooFieldsInvoice, OdooFieldsPartner

# Invoice fields
OdooFieldsInvoice.ID             # "id"
OdooFieldsInvoice.NAME           # "name"
OdooFieldsInvoice.INVOICE_DATE   # "invoice_date"
OdooFieldsInvoice.AMOUNT_TOTAL   # "amount_total"
OdooFieldsInvoice.PAYMENT_STATE  # "payment_state"
OdooFieldsInvoice.MOVE_TYPE      # "move_type"

# Partner fields
OdooFieldsPartner.ID             # "id"
OdooFieldsPartner.NAME           # "name"
OdooFieldsPartner.PHONE          # "phone"
OdooFieldsPartner.EMAIL          # "email"
```

### 3. **Odoo Actions** (`OdooActions`)

RPC method names for Odoo operations.

```python
from app.constants import OdooActions

OdooActions.SEARCH_READ          # "search_read"
OdooActions.READ                 # "read"
OdooActions.CREATE               # "create"
OdooActions.WRITE                # "write"
OdooActions.ACTION_POST          # "action_post" - Confirm invoice
```

### 4. **Odoo Enums**

Enum values for Odoo fields.

```python
from app.constants import OdooMoveTypes, OdooPaymentStates, OdooInvoiceStates

# Move types
OdooMoveTypes.OUT_INVOICE        # "out_invoice"
OdooMoveTypes.OUT_REFUND         # "out_refund"

# Payment states
OdooPaymentStates.PAID           # "paid"
OdooPaymentStates.NOT_PAID       # "not_paid"
OdooPaymentStates.PARTIAL        # "partial"

# Invoice states
OdooInvoiceStates.DRAFT          # "draft"
OdooInvoiceStates.POSTED         # "posted"
OdooInvoiceStates.CANCELLED      # "cancelled"
```

### 5. **API Timeouts** (`ApiTimeouts`)

HTTP request timeout values in seconds.

```python
from app.constants import ApiTimeouts

ApiTimeouts.DEFAULT              # 30 seconds
ApiTimeouts.LONG_REQUEST         # 60 seconds
ApiTimeouts.WHATSAPP_MEDIA_UPLOAD # 60 seconds - for media uploads
ApiTimeouts.ODOO_PDF_FETCH       # 30 seconds - for PDF retrieval
```

### 6. **API Defaults** (`ApiDefaults`)

Default limits and offsets for API queries.

```python
from app.constants import ApiDefaults

ApiDefaults.INVOICE_LIMIT        # 5 - Default invoices per query
ApiDefaults.ORDER_LIMIT          # 5 - Default orders per query
ApiDefaults.PAYMENT_LIMIT        # 3 - Default payments per query
ApiDefaults.LIST_INVOICE_LIMIT   # 100 - Max invoices for list endpoint
ApiDefaults.DEFAULT_OFFSET       # 0 - Starting offset for pagination
```

### 7. **Campaign Constants** (`CampaignDefaults`, `CampaignStatus`)

Campaign execution defaults and status values.

```python
from app.constants import CampaignDefaults, CampaignStatus

# Defaults
CampaignDefaults.BATCH_SIZE              # 50 - Messages per batch
CampaignDefaults.MESSAGE_DELAY_SECONDS   # 1.0 - Delay between messages
CampaignDefaults.MAX_RETRY_ATTEMPTS      # 3 - Retries before failure
CampaignDefaults.RETRY_BACKOFF_BASE      # 2 - Exponential backoff multiplier

# Status
CampaignStatus.PENDING                   # "pending"
CampaignStatus.RUNNING                   # "running"
CampaignStatus.COMPLETED                 # "completed"
CampaignStatus.FAILED                    # "failed"
```

### 8. **Message Status** (`DeliveryStatus`, `MessageRole`)

Message delivery and conversation statuses.

```python
from app.constants import DeliveryStatus, MessageRole

# Delivery status
DeliveryStatus.PENDING                   # "pending"
DeliveryStatus.SENT                      # "sent"
DeliveryStatus.DELIVERED                 # "delivered"
DeliveryStatus.READ                      # "read"
DeliveryStatus.FAILED                    # "failed"

# Message role
MessageRole.USER                         # "user"
MessageRole.ASSISTANT                    # "assistant"
MessageRole.SYSTEM                       # "system"
```

### 9. **WhatsApp Constants** (`WhatsAppApi`, `WhatsAppTemplate`)

WhatsApp Cloud API values.

```python
from app.constants import WhatsAppApi, WhatsAppTemplate

# API constants
WhatsAppApi.BASE_URL                     # "https://graph.facebook.com/v25.0"
WhatsAppApi.API_VERSION                  # "v25.0"
WhatsAppApi.MESSAGING_PRODUCT            # "whatsapp"
WhatsAppApi.MESSAGE_TYPE_TEXT            # "text"
WhatsAppApi.MESSAGE_TYPE_TEMPLATE        # "template"
WhatsAppApi.MESSAGE_TYPE_DOCUMENT        # "document"

# Template constants
WhatsAppTemplate.DEFAULT_LANGUAGE        # "en"
WhatsAppTemplate.PARAMETER_TYPE_TEXT     # "text"
WhatsAppTemplate.COMPONENT_TYPE_BODY     # "body"
```

### 10. **HTTP Status Codes** (`HttpStatusCodes`)

Standard HTTP response codes.

```python
from app.constants import HttpStatusCodes

HttpStatusCodes.OK                       # 200
HttpStatusCodes.CREATED                  # 201
HttpStatusCodes.BAD_REQUEST              # 400
HttpStatusCodes.UNAUTHORIZED             # 401
HttpStatusCodes.NOT_FOUND                # 404
HttpStatusCodes.INTERNAL_SERVER_ERROR    # 500
```

### 11. **Invoice Formatting** (`InvoiceDefaults`)

Invoice display and formatting constants.

```python
from app.constants import InvoiceDefaults

InvoiceDefaults.CURRENCY                 # "INR"
InvoiceDefaults.RUPEE_SYMBOL             # "₹"
```

### 12. **Pagination** (`Pagination`)

Pagination defaults.

```python
from app.constants import Pagination

Pagination.DEFAULT_LIMIT                 # 50
Pagination.DEFAULT_SKIP                  # 0
Pagination.MAX_LIMIT                     # 100
```

### 13. **Logging Messages** (`LogMessages`)

Standardized log messages for consistency.

```python
from app.constants import LogMessages

LogMessages.ODOO_CONTACT_CREATED         # "Contact created in Odoo"
LogMessages.ODOO_INVOICE_PDF_FETCHED     # "Invoice PDF fetched successfully from Odoo API"
LogMessages.WHATSAPP_MESSAGE_SENT        # "WhatsApp message sent"
LogMessages.CAMPAIGN_COMPLETED           # "Campaign job completed"
```

---

## Usage Examples by File Type

### Service Classes

```python
# app/services/odoo_service.py
from app.constants import OdooModels, OdooFieldsInvoice, OdooActions, ApiDefaults

def fetch_customer_invoices(self, partner_id: int, limit: int = ApiDefaults.INVOICE_LIMIT):
    return self._execute(
        OdooModels.ACCOUNT_MOVE,
        OdooActions.SEARCH_READ,
        [[
            [OdooFieldsInvoice.PARTNER_ID, "=", partner_id],
            [OdooFieldsInvoice.PAYMENT_STATE, "!=", "paid"]
        ]],
        {
            "fields": [OdooFieldsInvoice.ID, OdooFieldsInvoice.NAME, OdooFieldsInvoice.AMOUNT_TOTAL],
            "limit": limit
        }
    )
```

### Router Endpoints

```python
# app/routers/invoices.py
from app.constants import Pagination, HttpStatusCodes

@router.get("/", response_model=List[InvoiceOut])
def list_invoices(skip: int = Pagination.DEFAULT_SKIP, limit: int = Pagination.MAX_LIMIT):
    try:
        return odoo.list_all_invoices(limit=limit, offset=skip)
    except Exception as e:
        raise HTTPException(status_code=HttpStatusCodes.INTERNAL_SERVER_ERROR, detail=str(e))
```

### Campaign Jobs

```python
# app/jobs/campaign_job.py
from app.constants import CampaignDefaults, DeliveryStatus

def execute_campaign(campaign_id):
    batch_size = CampaignDefaults.BATCH_SIZE
    max_retries = CampaignDefaults.MAX_RETRY_ATTEMPTS
    msg.delivery_status = DeliveryStatus.SENT
```

### Whatsapp Service

```python
# app/services/whatsapp_service.py
from app.constants import WhatsAppApi, ApiTimeouts

class WhatsAppService:
    def __init__(self):
        self._url = f"{WhatsAppApi.BASE_URL}/{self._phone_number_id}/messages"
    
    def send_template(self, phone, template_name):
        payload = {
            WhatsAppApi.MESSAGING_PRODUCT: WhatsAppApi.MESSAGING_PRODUCT,
            "type": WhatsAppApi.MESSAGE_TYPE_TEMPLATE,
            "template": {"name": template_name}
        }
        response = requests.post(self._url, json=payload, timeout=ApiTimeouts.DEFAULT)
```

---

## Adding New Constants

When you need to add a new constant:

1. **Identify the category** - Where does it belong? (Odoo, API, Campaign, etc.)
2. **Add to appropriate class** in `app/constants.py`
3. **Use throughout codebase** instead of hardcoding the value
4. **Update this guide** with the new constant

### Example: Adding a New Timeout

```python
# In app/constants.py, add to ApiTimeouts class:
class ApiTimeouts:
    DEFAULT = 30
    LONG_REQUEST = 60
    WHATSAPP_MEDIA_UPLOAD = 60
    ODOO_PDF_FETCH = 30
    MY_NEW_API_TIMEOUT = 45  # ← New constant

# Use in code:
from app.constants import ApiTimeouts
response = requests.get(url, timeout=ApiTimeouts.MY_NEW_API_TIMEOUT)
```

---

## Files Already Refactored

✅ `app/constants.py` - Created with all constants
✅ `app/services/odoo_service.py` - Uses Odoo constants
✅ `app/services/whatsapp_service.py` - Uses WhatsApp constants
✅ `app/jobs/campaign_job.py` - Uses campaign constants
✅ `app/routers/invoices.py` - Uses HTTP status and pagination constants

---

## Files Still Using Hardcoded Values

The following files still have some hardcoded values and should be refactored next:

- `app/routers/whatsapp.py` - Webhook handling
- `app/routers/campaigns.py` - Campaign endpoints
- `app/routers/contacts.py` - Contact endpoints
- `app/services/ai_service.py` - AI service
- `app/models/` - Model definitions
- `app/schemas/` - Pydantic schemas

---

## Benefits Summary

| Before | After |
|--------|-------|
| Hardcoded `"account.move"` in 10 files | Single `OdooModels.ACCOUNT_MOVE` |
| Magic number `30` for timeouts scattered | Centralized `ApiTimeouts.DEFAULT` |
| Copy-paste field lists | `OdooFieldsInvoice.*` constants |
| Inconsistent HTTP status codes | `HttpStatusCodes.OK`, `NOT_FOUND`, etc. |
| Hard to find where values are used | `grep OdooModels.ACCOUNT_MOVE` finds all |

---

## Questions?

Refer to specific constant classes in `app/constants.py` for the full list of available values.

Import the constants you need and use them throughout your code!

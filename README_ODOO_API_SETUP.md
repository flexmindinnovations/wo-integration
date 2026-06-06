# Odoo Invoice API Setup - Complete Guide

## What We're Building

A **secure, token-based API endpoint** in Odoo that allows your WhatsApp service to fetch professional invoice PDFs directly from Odoo.

### Architecture:

```
WhatsApp Message "send invoice"
        ↓
    Your Python App
        ↓
  Odoo Custom API Endpoint (/api/invoice/pdf/{id})
        ↓
   Validates API Token
        ↓
  Renders Invoice PDF using Odoo's official report
        ↓
  Returns PDF to Python App
        ↓
  Uploads to Meta & sends via WhatsApp
```

---

## Files You Need

### 📦 Provided Files (in your project):

1. **whatsapp_invoice_api_manifest.py** → `__manifest__.py`
2. **whatsapp_invoice_api_init.py** → `__init__.py`
3. **whatsapp_invoice_api_controllers_init.py** → `controllers/__init__.py`
4. **whatsapp_invoice_api_controller.py** → `controllers/main.py`
5. **whatsapp_invoice_api_access.csv** → `security/ir.model.access.csv`
6. **updated_odoo_service_method.py** → Replace method in `app/services/odoo_service.py`

### 📋 Guide Documents:

1. **ODOO_MODULE_INSTALLATION_GUIDE.md** - Step-by-step Odoo setup
2. **IMPLEMENTATION_CHECKLIST.md** - Complete implementation checklist
3. **README_ODOO_API_SETUP.md** - This file

---

## Quick Start (3 Simple Steps)

### Step 1: Create Odoo Module (5 min)

1. In Odoo file manager, create folder: `addons/whatsapp_invoice_api/`
2. Create the 5 files listed above using the provided content
3. Go to Apps → Update Apps List → Search for `whatsapp_invoice_api` → Install

### Step 2: Create API Token (2 min)

1. In Odoo: Settings → Users → Create/Edit user
2. Add field `api_token` with value: `whatsapp_api_token_abc123xyz`
3. Save

### Step 3: Update Python Code (3 min)

1. Replace `get_invoice_pdf()` method in `app/services/odoo_service.py`
2. Commit and push: `git push origin main`
3. Wait for Render deployment (5-10 min)

---

## Detailed Steps

### Odoo Setup

**Full guide**: See `ODOO_MODULE_INSTALLATION_GUIDE.md`

1. Create module file structure in Odoo addons
2. Copy contents from provided files into Odoo
3. Install module from Apps menu
4. Create API token in user settings
5. Test with: `/api/invoice/pdf/test?token=YOUR_TOKEN`

### Python Code Update

**File**: `app/services/odoo_service.py`

**Replace method**: `get_invoice_pdf(self, invoice_id: int) -> bytes`

**With content from**: `updated_odoo_service_method.py`

**Key changes**:
- Uses new API endpoint: `/api/invoice/pdf/{id}`
- Token-based authentication
- Better error handling
- Logs show `source: "odoo_api"`

### Deploy

```bash
git add app/services/odoo_service.py
git commit -m "feat: use custom Odoo API for invoice PDFs"
git push origin main
```

---

## Testing

### Test 1: API Endpoint

```bash
curl "https://your-odoo.odoo.com/api/invoice/pdf/test?token=YOUR_TOKEN"
```

Expected: `Success! API is working...`

### Test 2: Get PDF

```bash
curl "https://your-odoo.odoo.com/api/invoice/pdf/3?token=YOUR_TOKEN" \
  --output test-invoice.pdf
```

Expected: Valid PDF file downloads

### Test 3: Full Integration

Send WhatsApp message: `"show me my invoice"`

Expected:
- ✅ AI response with invoice details
- ✅ Professional PDF from Odoo attached
- ✅ Proper filename
- ✅ Rupee symbol (₹) displayed

---

## What Changed

### Before (Fallback):
- Generated PDF locally
- Basic formatting
- No Odoo integration

### After (Custom API):
- Fetches Odoo's official report
- Professional formatting
- Proper company branding
- Official invoice document

---

## Security

✅ **Token-based authentication** - Only valid token can access  
✅ **User context** - PDFs respects user permissions  
✅ **Read-only** - API only reads data, no modifications  
✅ **No database changes** - Safe implementation  

---

## Troubleshooting Quick Links

- **Token invalid** → Check `.env` ODOO_API_KEY matches Odoo user token
- **Invoice not found** → Verify ID exists and invoice is "posted"
- **PDF render error** → Check Odoo logs (Settings → Technical → Logs)
- **Connection failed** → Verify ODOO_URL is correct and reachable

---

## Performance

- **API response time**: ~500ms - 2s per invoice
- **Fallback**: If API fails, system falls back to PDF generation
- **Caching**: Could be added later if needed

---

## Next Actions

1. [ ] Copy provided files to Odoo addons
2. [ ] Install module in Odoo
3. [ ] Create API token
4. [ ] Test API endpoint
5. [ ] Update Python code
6. [ ] Deploy and test full flow
7. [ ] Monitor logs for any issues

---

## File Reference

### Module Structure
```
whatsapp_invoice_api/
├── __init__.py
│   └── from . import controllers
│
├── __manifest__.py
│   └── Module metadata, dependencies, data files
│
├── controllers/
│   ├── __init__.py
│   │   └── from . import main
│   │
│   └── main.py
│       └── WhatsAppInvoiceAPI controller with:
│           - Token validation
│           - PDF generation
│           - Error handling
│
└── security/
    └── ir.model.access.csv
        └── Access control for account.move
```

### API Endpoints

**Get Invoice PDF**:
- Method: GET
- URL: `/api/invoice/pdf/<invoice_id>`
- Query: `?token=YOUR_API_TOKEN`
- Response: PDF file

**Test Endpoint**:
- Method: GET
- URL: `/api/invoice/pdf/test`
- Query: `?token=YOUR_API_TOKEN`
- Response: "Success! API is working..."

---

## Support

If something doesn't work:

1. Check Odoo logs: Settings → Technical → Logs
2. Test API manually with curl
3. Verify module is installed in Apps
4. Check authentication token
5. Review error messages in logs

---

## Summary

You're implementing a professional, secure way to fetch invoice PDFs from Odoo. This is the recommended approach for production systems because:

✅ Uses Odoo's official reports  
✅ Secure token-based auth  
✅ Professional formatting  
✅ Scalable architecture  
✅ Falls back gracefully  

Total implementation time: **~20 minutes**

---

**Ready to start?** Begin with Step 1 in ODOO_MODULE_INSTALLATION_GUIDE.md!

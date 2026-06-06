# WhatsApp Invoice PDF API - Implementation Checklist

## Overview

This guide walks you through implementing a **custom Odoo API module** to securely fetch invoice PDFs for WhatsApp delivery.

### What You'll Get:
✅ Professional invoice PDFs directly from Odoo  
✅ Token-based authentication (secure)  
✅ No more fallback PDF generation  
✅ Proper invoice formatting with Odoo's official reports  

---

## Phase 1: Odoo Module Installation (5-10 minutes)

### ☐ 1.1 Create Module Files

Create folder structure in Odoo addons directory:
```
addons/whatsapp_invoice_api/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py
└── security/
    └── ir.model.access.csv
```

**Files to create:**
- [ ] `__manifest__.py` - Module metadata
- [ ] `__init__.py` - Module package init  
- [ ] `controllers/__init__.py` - Controllers package init
- [ ] `controllers/main.py` - API endpoint with token auth
- [ ] `security/ir.model.access.csv` - Access control

📄 **Reference**: See ODOO_MODULE_INSTALLATION_GUIDE.md for file contents

### ☐ 1.2 Install Module in Odoo

1. [ ] Go to **Apps** menu
2. [ ] Click **Update Apps List**
3. [ ] Search for `whatsapp_invoice_api`
4. [ ] Click **Install**

**Verification**: Check that module status shows "Installed"

### ☐ 1.3 Generate API Token

1. [ ] Go to **Settings → Users & Companies → Users**
2. [ ] Create new user OR select existing user
3. [ ] Add API token field with value (e.g., `whatsapp_api_token_abc123xyz`)
4. [ ] Save

**Note**: The API token should match your `ODOO_API_KEY` in your Python `.env`

### ☐ 1.4 Test API Endpoint

Run this command to verify the API works:

```bash
curl "https://your-odoo-instance.odoo.com/api/invoice/pdf/test?token=YOUR_API_TOKEN"
```

Expected response:
```
Success! API is working. Authenticated as: [User Name]
```

If this fails:
- [ ] Check API token is correct
- [ ] Verify user is active in Odoo
- [ ] Check module is installed

---

## Phase 2: Update Python Code (10 minutes)

### ☐ 2.1 Update OdooService.get_invoice_pdf()

In your project: `app/services/odoo_service.py`

1. [ ] Find the `get_invoice_pdf()` method
2. [ ] Replace entire method with code from `updated_odoo_service_method.py`
3. [ ] Save file

### ☐ 2.2 No Other Changes Needed

The rest of the code remains the same:
- [ ] PDF generation fallback still exists (as backup)
- [ ] No changes to webhook handlers
- [ ] No changes to AI service

---

## Phase 3: Deploy & Test (5 minutes)

### ☐ 3.1 Commit Changes

```bash
git add app/services/odoo_service.py
git commit -m "feat: use custom Odoo API endpoint for invoice PDF retrieval"
git push origin main
```

### ☐ 3.2 Wait for Render Deployment

Wait 5-10 minutes for the build to complete on Render.

### ☐ 3.3 Test Full Flow

Send WhatsApp message: `"show me my invoice"`

Expected result:
- ✅ Text response with invoice details
- ✅ PDF attachment from **Odoo's official report** (not generated)
- ✅ Professional formatting with Odoo branding (if configured)

**Check logs** for:
- "Invoice PDF fetched successfully from Odoo API"
- "source": "odoo_api"

---

## Troubleshooting

### Issue: "Odoo API token invalid"

**Solutions:**
- [ ] Verify token in settings/user matches `.env` `ODOO_API_KEY`
- [ ] Check user account is active in Odoo
- [ ] Test with `/api/invoice/pdf/test` endpoint first

### Issue: "Invoice not found (404)"

**Solutions:**
- [ ] Verify invoice ID exists in Odoo
- [ ] Check invoice is in "posted" state
- [ ] Verify user has read access to that invoice

### Issue: "Could not render PDF"

**Solutions:**
- [ ] Check `account` module is installed in Odoo
- [ ] Try generating PDF manually in Odoo first
- [ ] Verify `account.report_invoice` report exists
- [ ] Check Odoo logs in **Settings → Technical → Logs**

### Issue: "Cannot reach Odoo instance"

**Solutions:**
- [ ] Verify `ODOO_URL` is correct in `.env`
- [ ] Check firewall/network connectivity
- [ ] Ensure Odoo instance is running/accessible

---

## Success Criteria

Once everything is working:

✅ API endpoint responds to test request  
✅ PDF is fetched from Odoo (not generated)  
✅ Logs show "source": "odoo_api"  
✅ Professional invoice PDFs sent via WhatsApp  
✅ All invoice fields display correctly with rupee symbol  

---

## Rollback (If Needed)

If you need to revert to PDF generation fallback:

1. [ ] Revert the code change: `git revert HEAD`
2. [ ] Push: `git push origin main`
3. [ ] System will use `generate_invoice_pdf()` fallback

---

## Next Steps After Success

Once the Odoo API integration is working:

1. **Monitor logs** for any errors
2. **Test with different invoices** to ensure compatibility
3. **Optimize** - Consider caching PDF results if needed
4. **Optional**: Remove `generate_invoice_pdf()` method if no longer needed

---

## Support

If you encounter issues:

1. [ ] Check Odoo logs: **Settings → Technical → Logs**
2. [ ] Test API manually: `/api/invoice/pdf/test?token=YOUR_TOKEN`
3. [ ] Verify module installation in **Apps** menu
4. [ ] Check `.env` configuration (ODOO_URL, ODOO_API_KEY)
5. [ ] Review application logs in Render dashboard

